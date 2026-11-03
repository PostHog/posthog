import { withFileLock } from '@/core/file-lock'
import type { Runtime } from '@/core/runtime'
import { accessKeyFromStorage, type AccessKey, type AccessKeyStorage, type LogoutOutcome } from '@/posthog/access-key'
import { FileStore } from '@/posthog/credential-store/file'
import { KeychainStore } from '@/posthog/credential-store/keychain'
import { openStore } from '@/posthog/credential-store/open'
import { hostKey, type HostKey } from '@/posthog/host'
import { loginFor, readSettings, withLogin, writeSettings, type HogSettings } from '@/posthog/settings'

// settings.json and the credentials file hold every host's login, so each write reads them, changes
// one entry and writes them back. The lock keeps two hog processes from dropping each other's entry.
const LOGINS_LOCK = 'logins.lock'

export interface LoggedOutHost {
    host: string
    revokeUrl: string | null
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
    await withFileLock(runtime, LOGINS_LOCK, async () => {
        await store.write(key.host, key.secret(), { removeIfLate: options.removeIfLate })
        const settings = withLogin(await readSettings(runtime), key.host, key.record(store.kind))
        await writeSettings(runtime, options.lastLogin ? { ...settings, host: key.host } : settings)
    })
}

// Resolves to false when hog had no login for the host.
export async function removeLogin(runtime: Runtime, login: StoredLogin): Promise<boolean> {
    const { host } = login.key
    return withFileLock(runtime, LOGINS_LOCK, async () => {
        const removed = await login.store.remove(host)
        const settings = withLogin(await readSettings(runtime), host, undefined)
        const lastLogin = settings.host !== undefined && hostKey(settings.host) === hostKey(host)
        await writeSettings(runtime, lastLogin ? { logins: settings.logins } : settings)
        return removed
    })
}

// Logs this machine out of `host`: the key revokes itself where it can, and hog removes its
// stored copy. Resolves to undefined when hog had no login to remove.
export async function logout(runtime: Runtime, host: string): Promise<LogoutOutcome | undefined> {
    const login = await readLogin(runtime, await readSettings(runtime), host)
    if (!login) {
        return undefined
    }
    const [outcome, removed] = await Promise.all([login.key.logout(runtime), removeLogin(runtime, login)])
    return removed ? outcome : undefined
}

// Logs this machine out of every host in settings.json or the credentials file. For each host it
// also removes the secret from the store settings.json doesn't name, such as a keychain item left
// behind when a login fell back to the file.
export async function logoutAll(runtime: Runtime): Promise<LoggedOutHost[]> {
    const settings = await readSettings(runtime)
    const file = new FileStore(runtime)
    const keychain = new KeychainStore(runtime)
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
        // A machine without a usable keychain can't hold a leftover item there.
        const leftovers = await withFileLock(runtime, LOGINS_LOCK, () =>
            Promise.all([file.remove(host), keychain.remove(host).catch(() => false)])
        )
        if (outcome || leftovers.includes(true)) {
            loggedOut.push({ host, revokeUrl: outcome?.revokeUrl ?? null })
        }
    }
    return loggedOut
}
