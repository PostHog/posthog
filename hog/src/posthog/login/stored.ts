import { withFileLock } from '@/core/file-lock'
import type { Runtime } from '@/core/runtime'
import { accessKeyFromStorage, type AccessKey, type AccessKeyStorage, type LogoutOutcome } from '@/posthog/access-key'
import type { FileStore } from '@/posthog/credential-store/file'
import type { KeychainStore } from '@/posthog/credential-store/keychain'
import { openStore } from '@/posthog/credential-store/open'
import { hostKey } from '@/posthog/host'
import { loginFor, readSettings, withLogin, writeSettings, type HogSettings } from '@/posthog/settings'

// settings.json and the credentials file hold every host's login, so each write reads them, changes
// one entry and writes them back. The lock keeps two hog processes from dropping each other's entry.
const LOGINS_LOCK = 'logins.lock'

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
