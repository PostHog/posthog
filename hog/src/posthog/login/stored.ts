import { HogError } from '@/core/errors'
import { withFileLock } from '@/core/file-lock'
import type { Runtime } from '@/core/runtime'
import { accessKeyFromStorage, type AccessKey, type AccessKeyStorage, type LogoutOutcome } from '@/posthog/access-key'
import { FileStore } from '@/posthog/credential-store/file'
import { KeychainStore } from '@/posthog/credential-store/keychain'
import { openStore } from '@/posthog/credential-store/open'
import { hostKey, type Host, type HostKey } from '@/posthog/host'
import { withLoginLock } from '@/posthog/oauth'
import { loginFor, readSettings, withLogin, writeSettings, type HogSettings } from '@/posthog/settings'

// settings.json and the credentials file hold every host's login, so each write reads them, changes
// one entry and writes them back. The lock keeps two hog processes from dropping each other's entry.
const LOGINS_LOCK = 'logins.lock'

export interface LoggedOut extends LogoutOutcome {
    // Why hog couldn't remove the keychain item a file login left behind. Null when there was none.
    keychainLeftover: string | null
}

export interface LoggedOutHost extends LoggedOut {
    host: Host
}

export interface StoredLogin {
    key: AccessKey
    store: KeychainStore | FileStore
}

export async function readLogin(runtime: Runtime, settings: HogSettings, host: Host): Promise<StoredLogin | undefined> {
    const record = loginFor(settings, host)
    if (!record) {
        return undefined
    }
    const store = openStore(runtime, record.store)
    const secret = await store.read(host)
    const key = secret && accessKeyFromStorage(record, secret)
    return key ? { key, store } : undefined
}

export function loginStorage(runtime: Runtime, login: StoredLogin): AccessKeyStorage {
    const { host } = login.key
    return {
        reread: async () => (await readLogin(runtime, await readSettings(runtime), host))?.key,
        save: (key) => writeLogin(runtime, login.store, key),
    }
}

// Writes the secrets first, so settings.json never names a login whose secrets aren't stored yet.
// The settings are read again just before the write, so a change another hog process made to a
// different host's login survives.
export async function writeLogin(
    runtime: Runtime,
    store: KeychainStore | FileStore,
    key: AccessKey,
    options: { lastLogin?: boolean; removeIfLate?: boolean; keychainLeftover?: boolean } = {}
): Promise<void> {
    await withFileLock(runtime, LOGINS_LOCK, async () => {
        await store.write(key.host, key.secret(), { removeIfLate: options.removeIfLate })
        const current = await readSettings(runtime)
        const previous = loginFor(current, key.host)
        const record = key.record(store.kind)
        const keychainLeftover =
            store.kind === 'file' &&
            (options.keychainLeftover === true || previous?.store === 'keychain' || previous?.keychainLeftover === true)
        const settings = withLogin(current, key.host, keychainLeftover ? { ...record, keychainLeftover } : record)
        await writeSettings(runtime, options.lastLogin ? { ...settings, host: key.host } : settings)
    })
}

// Resolves to false when the store held nothing for the host.
export async function removeLogin(runtime: Runtime, host: Host, store: KeychainStore | FileStore): Promise<boolean> {
    return withFileLock(runtime, LOGINS_LOCK, async () => {
        const removed = await store.remove(host)
        const settings = withLogin(await readSettings(runtime), host, undefined)
        const lastLogin = settings.host !== undefined && hostKey(settings.host) === hostKey(host)
        await writeSettings(runtime, lastLogin ? { logins: settings.logins } : settings)
        return removed
    })
}

// Logs this machine out of `host`: the key revokes itself where it can, and hog removes its
// stored copy. Resolves to undefined when hog had no login to remove.
// Under the renewal lock, so a renewal in another hog process can neither restore the login after
// this removes it, nor rotate the refresh token this revokes.
export async function logout(runtime: Runtime, host: Host): Promise<LoggedOut | undefined> {
    return withLoginLock(runtime, host, async () => {
        const settings = await readSettings(runtime)
        const record = loginFor(settings, host)
        const login = await readLogin(runtime, settings, host)
        if (!login) {
            if (!record) {
                return undefined
            }
            // The store can hold an item hog can't read, such as a key an older hog accepted, and
            // the file entry can be gone while the record still names a keychain item left behind.
            // Both are removed, so logout leaves no secret behind.
            const removed = await removeLogin(runtime, host, openStore(runtime, record.store))
            if (!removed && !record.keychainLeftover) {
                return undefined
            }
            const leftover = record.keychainLeftover ? await removeKeychainLeftover(runtime, host) : null
            return { revoked: null, revokeUrl: null, keychainLeftover: leftover }
        }
        const [outcome, removed] = await Promise.all([
            login.key.logout(runtime),
            removeLogin(runtime, host, login.store),
        ])
        if (!removed) {
            return undefined
        }
        const leftover = record?.keychainLeftover ? await removeKeychainLeftover(runtime, host) : null
        return { ...outcome, keychainLeftover: leftover }
    })
}

// Resolves to why the removal failed, or null once no item is left.
async function removeKeychainLeftover(runtime: Runtime, host: Host): Promise<string | null> {
    try {
        await new KeychainStore(runtime).remove(host)
        return null
    } catch (error) {
        return error instanceof Error ? error.message : String(error)
    }
}

// For a host settings.json names no keychain item for. A machine without a usable keychain can't
// hold one, so only a refused or abandoned removal counts as a failure.
async function sweepKeychain(runtime: Runtime, host: Host): Promise<{ removed: boolean; error: string | null }> {
    try {
        return { removed: await new KeychainStore(runtime).remove(host), error: null }
    } catch (error) {
        if (error instanceof HogError && error.code === 'keychain_unavailable') {
            return { removed: false, error: null }
        }
        return { removed: false, error: error instanceof Error ? error.message : String(error) }
    }
}

// Logs this machine out of every host in settings.json or the credentials file. It also removes the
// entries of the credentials file and the keychain items that settings.json doesn't name, such as a
// keychain item from before settings.json was lost.
export async function logoutAll(runtime: Runtime): Promise<LoggedOutHost[]> {
    const settings = await readSettings(runtime)
    const file = new FileStore(runtime)
    const hosts = new Map<HostKey, Host>()
    const recorded = Object.values(settings.logins ?? {}).flatMap((record) => (record ? [record.host] : []))
    for (const host of [...recorded, ...(await file.hosts())]) {
        if (!hosts.has(hostKey(host))) {
            hosts.set(hostKey(host), host)
        }
    }
    const loggedOut: LoggedOutHost[] = []
    for (const host of hosts.values()) {
        const record = loginFor(settings, host)
        const outcome = await logout(runtime, host)
        const orphan = await withFileLock(runtime, LOGINS_LOCK, () => file.remove(host))
        // Logout already handled a keychain login and a marked leftover.
        const swept =
            record?.store !== 'keychain' && !record?.keychainLeftover
                ? await sweepKeychain(runtime, host)
                : { removed: false, error: null }
        if (outcome || orphan || swept.removed || swept.error) {
            const base = outcome ?? { revoked: null, revokeUrl: null, keychainLeftover: null }
            loggedOut.push({ ...base, keychainLeftover: base.keychainLeftover ?? swept.error, host })
        }
    }
    await withFileLock(runtime, LOGINS_LOCK, () => file.removeUnreadable())
    return loggedOut
}
