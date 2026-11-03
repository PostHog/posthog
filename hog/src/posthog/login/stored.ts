import type { Runtime } from '@/core/runtime'
import { accessKeyFromStorage, type AccessKey, type AccessKeyStorage, type LogoutOutcome } from '@/posthog/access-key'
import { FileStore } from '@/posthog/credential-store/file'
import { KeychainStore } from '@/posthog/credential-store/keychain'
import { openStore } from '@/posthog/credential-store/open'
import { hostKey, type HostKey } from '@/posthog/host'
import { loginFor, readSettings, withLogin, writeSettings, type HogSettings } from '@/posthog/settings'

export interface LoggedOut extends LogoutOutcome {
    // Why hog couldn't remove the keychain item a file login left behind. Null when there was none.
    keychainLeftover: string | null
}

export interface LoggedOutHost extends LoggedOut {
    host: string
}

export interface StoredLogin {
    key: AccessKey
    store: KeychainStore | FileStore
}

export async function readLogin(
    runtime: Runtime,
    settings: HogSettings,
    host: string
): Promise<StoredLogin | undefined> {
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
    options: { lastLogin?: boolean; removeIfLate?: boolean } = {}
): Promise<void> {
    await store.write(key.host, key.secret(), { removeIfLate: options.removeIfLate })
    const current = await readSettings(runtime)
    const previous = loginFor(current, key.host)
    const record = key.record(store.kind)
    const keychainLeftover =
        store.kind === 'file' && (previous?.store === 'keychain' || previous?.keychainLeftover === true)
    const settings = withLogin(current, key.host, keychainLeftover ? { ...record, keychainLeftover } : record)
    await writeSettings(runtime, options.lastLogin ? { ...settings, host: key.host } : settings)
}

// Resolves to false when hog had no login for the host.
export async function removeLogin(runtime: Runtime, login: StoredLogin): Promise<boolean> {
    const { host } = login.key
    const removed = await login.store.remove(host)
    const settings = withLogin(await readSettings(runtime), host, undefined)
    const lastLogin = settings.host !== undefined && hostKey(settings.host) === hostKey(host)
    await writeSettings(runtime, lastLogin ? { logins: settings.logins } : settings)
    return removed
}

// Logs this machine out of `host`: the key revokes itself where it can, and hog removes its
// stored copy. Resolves to undefined when hog had no login to remove.
export async function logout(runtime: Runtime, host: string): Promise<LoggedOut | undefined> {
    const settings = await readSettings(runtime)
    const login = await readLogin(runtime, settings, host)
    if (!login) {
        return undefined
    }
    const [outcome, removed] = await Promise.all([login.key.logout(runtime), removeLogin(runtime, login)])
    if (!removed) {
        return undefined
    }
    const leftover = loginFor(settings, host)?.keychainLeftover ? await removeKeychainLeftover(runtime, host) : null
    return { ...outcome, keychainLeftover: leftover }
}

async function removeKeychainLeftover(runtime: Runtime, host: string): Promise<string | null> {
    try {
        await new KeychainStore(runtime).remove(host)
        return null
    } catch (error) {
        return error instanceof Error ? error.message : String(error)
    }
}

// Logs this machine out of every host in settings.json or the credentials file, and removes the
// entries of the credentials file that settings.json doesn't name.
export async function logoutAll(runtime: Runtime): Promise<LoggedOutHost[]> {
    const settings = await readSettings(runtime)
    const file = new FileStore(runtime)
    const hosts = new Map<HostKey, string>()
    const recorded = Object.values(settings.logins ?? {}).flatMap((record) => (record ? [record.host] : []))
    for (const host of [...recorded, ...(await file.hosts())]) {
        if (!hosts.has(hostKey(host))) {
            hosts.set(hostKey(host), host)
        }
    }
    const loggedOut: LoggedOutHost[] = []
    for (const host of hosts.values()) {
        const outcome = await logout(runtime, host)
        const orphan = await file.remove(host)
        if (outcome || orphan) {
            loggedOut.push(
                outcome ? { ...outcome, host } : { host, revoked: null, revokeUrl: null, keychainLeftover: null }
            )
        }
    }
    return loggedOut
}
