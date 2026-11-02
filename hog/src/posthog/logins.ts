import { withFileLock } from '@/core/file-lock'
import type { Runtime } from '@/core/runtime'

import { credentialFromStorage, type Credential, type CredentialStorage } from './credential'
import { hostKey, openStore, type FileStore, type KeychainStore } from './credential-store'
import { loginFor, readSettings, withLogin, writeSettings, type HogSettings } from './settings'

// settings.json and the credentials file hold every host's login, so each write reads them, changes
// one entry and writes them back. The lock keeps two hog processes from dropping each other's entry.
const LOGINS_LOCK = 'logins.lock'

// A login hog stored, and the store that holds its secrets.
export interface StoredLogin {
    credential: Credential
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
    const credential = secret && credentialFromStorage(hostKey(host), record, secret)
    return credential ? { credential, store } : undefined
}

// How a login's credential reads and saves its stored copy when it renews itself.
export function loginStorage(runtime: Runtime, login: StoredLogin): CredentialStorage {
    const { host } = login.credential
    return {
        reread: async () => (await readLogin(runtime, await readSettings(runtime), host))?.credential,
        save: (credential) => writeLogin(runtime, login.store, credential),
    }
}

// Writes the secrets first, so settings.json never names a login whose secrets aren't stored yet.
// The settings are read again just before the write, so a change another hog process made to a
// different host's login survives.
export async function writeLogin(
    runtime: Runtime,
    store: KeychainStore | FileStore,
    credential: Credential,
    options: { lastLogin?: boolean } = {}
): Promise<void> {
    await withFileLock(runtime, LOGINS_LOCK, async () => {
        await store.write(credential.host, credential.secret())
        const settings = withLogin(await readSettings(runtime), credential.host, credential.record(store.kind))
        await writeSettings(runtime, options.lastLogin ? { ...settings, host: credential.host } : settings)
    })
}

// Removes the login's secrets and its record. Resolves to false when hog had no login for the host.
export async function removeLogin(runtime: Runtime, login: StoredLogin): Promise<boolean> {
    const { host } = login.credential
    return withFileLock(runtime, LOGINS_LOCK, async () => {
        const removed = await login.store.remove(host)
        const settings = withLogin(await readSettings(runtime), host, undefined)
        const lastLogin = settings.host !== undefined && hostKey(settings.host) === hostKey(host)
        await writeSettings(runtime, lastLogin ? { logins: settings.logins } : settings)
        return removed
    })
}
