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
    const { projectId } = credential
    if (credential.type === 'personal_api_key') {
        return [{ apiKey: credential.apiKey }, { store: store.kind, type: credential.type, projectId }]
    }
    const { accessToken, refreshToken, expiresAt, scopes, loginId } = credential
    return [
        { accessToken, refreshToken },
        { store: store.kind, type: credential.type, projectId, expiresAt, scopes, loginId },
    ]
}

// A secret of the wrong kind for its record, such as one an older hog wrote, reads as no login.
function joinLogin(host: string, record: LoginRecord, secret: StoredSecret): StoredCredential | undefined {
    const { projectId } = record
    if (record.type === 'personal_api_key' && 'apiKey' in secret) {
        return { type: record.type, host, projectId, apiKey: secret.apiKey }
    }
    if (record.type === 'oauth' && 'accessToken' in secret) {
        const { expiresAt, scopes, loginId } = record
        return { type: record.type, host, projectId, expiresAt, scopes, loginId, ...secret }
    }
    return undefined
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
    const credential = secret && joinLogin(hostKey(host), record, secret)
    return credential ? { credential, store } : undefined
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
