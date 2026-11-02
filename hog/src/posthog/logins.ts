import type { Runtime } from '@/core/runtime'

import {
    hostKey,
    openStore,
    type FileStore,
    type KeychainStore,
    type StoredCredential,
    type StoredSecret,
} from './credential-store'
import { loginFor, readSettings, withLogin, writeSettings, type HogSettings, type LoginRecord } from './settings'

// A login hog stored, and the store that holds its secrets.
export interface StoredLogin {
    credential: StoredCredential
    store: KeychainStore | FileStore
}

function splitLogin(credential: StoredCredential, store: KeychainStore | FileStore): [StoredSecret, LoginRecord] {
    return [
        { apiKey: credential.apiKey },
        { store: store.kind, type: credential.type, projectId: credential.projectId },
    ]
}

function joinLogin(host: string, record: LoginRecord, secret: StoredSecret): StoredCredential {
    return { type: record.type, host, projectId: record.projectId, apiKey: secret.apiKey }
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
    return secret ? { credential: joinLogin(hostKey(host), record, secret), store } : undefined
}

// Writes the secrets first, so settings.json never names a login whose secrets aren't stored yet.
// The settings are read again just before the write, so a change another hog process made to a
// different host's login survives.
export async function writeLogin(
    runtime: Runtime,
    store: KeychainStore | FileStore,
    credential: StoredCredential,
    options: { lastLogin?: boolean } = {}
): Promise<void> {
    const [secret, record] = splitLogin(credential, store)
    await store.write(credential.host, secret)
    const settings = withLogin(await readSettings(runtime), credential.host, record)
    await writeSettings(runtime, options.lastLogin ? { ...settings, host: credential.host } : settings)
}

// Removes the login's secrets and its record. Resolves to false when hog had no login for the host.
export async function removeLogin(runtime: Runtime, login: StoredLogin): Promise<boolean> {
    const { host } = login.credential
    const removed = await login.store.remove(host)
    const settings = withLogin(await readSettings(runtime), host, undefined)
    const lastLogin = settings.host !== undefined && hostKey(settings.host) === hostKey(host)
    await writeSettings(runtime, lastLogin ? { logins: settings.logins } : settings)
    return removed
}
