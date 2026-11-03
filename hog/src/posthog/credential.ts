import type { Runtime } from '@/core/runtime'

import { hostUrl, type StoreChoice, type StoredSecret } from './credential-store'
import { OAuthLogin } from './oauth'
import type { LoginRecord } from './settings'

// What `hog auth status` shows about a credential.
export interface CredentialStatus {
    kind: 'personal_api_key' | 'oauth'
    // Null for a personal API key, whose scopes only PostHog knows.
    scopes: string[] | null
    // Epoch milliseconds. Null for a credential that doesn't expire.
    expiresAt: number | null
}

// What logging out did in PostHog.
export interface LogoutOutcome {
    // Whether PostHog revoked the login. Null for a credential hog can't revoke.
    revoked: boolean | null
    // Where to delete a credential that keeps working after logout.
    revokeUrl: string | null
}

// How a stored credential reaches its stored copy, so a renewal can read the latest one and save
// the new one.
export interface CredentialStorage {
    reread(): Promise<Credential | undefined>
    save(credential: Credential): Promise<void>
}

// A credential hog can send to PostHog. Each kind owns how it authenticates, renews, logs out and
// is stored, so callers never branch on the kind.
export interface Credential {
    readonly host: string
    readonly projectId: string
    // What PostHog takes as the bearer token.
    readonly token: string
    // Stays the same for the whole login, unlike an OAuth token, which changes on each renewal.
    readonly loginKey: string
    // A credential that works for the rest of the command, renewed if it is about to expire.
    fresh(runtime: Runtime, storage: CredentialStorage): Promise<Credential>
    status(): CredentialStatus
    logout(runtime: Runtime): Promise<LogoutOutcome>
    // The credential store keeps the secret, and settings.json keeps the record.
    secret(): StoredSecret
    record(store: StoreChoice): LoginRecord
}

export class PersonalApiKey implements Credential {
    constructor(
        readonly host: string,
        readonly projectId: string,
        readonly token: string
    ) {}

    get loginKey(): string {
        return this.token
    }

    async fresh(): Promise<Credential> {
        return this
    }

    status(): CredentialStatus {
        return { kind: 'personal_api_key', scopes: null, expiresAt: null }
    }

    // A personal API key can't be revoked from hog, so logout says where to delete it.
    async logout(): Promise<LogoutOutcome> {
        return {
            revoked: null,
            revokeUrl: hostUrl(this.host, 'settings/user-api-keys').toString(),
        }
    }

    secret(): StoredSecret {
        return { apiKey: this.token }
    }

    record(store: StoreChoice): LoginRecord {
        return { store, type: 'personal_api_key', projectId: this.projectId }
    }
}

// The one place that reads the stored kind. A secret of the wrong kind for its record, such as one
// an older hog wrote, reads as no login.
export function credentialFromStorage(host: string, record: LoginRecord, secret: StoredSecret): Credential | undefined {
    if (record.type === 'personal_api_key' && 'apiKey' in secret) {
        return new PersonalApiKey(host, record.projectId, secret.apiKey)
    }
    if (record.type === 'oauth' && 'accessToken' in secret) {
        const { projectId, expiresAt, scopes, loginId } = record
        return new OAuthLogin({ host, projectId, expiresAt, scopes, loginId, ...secret })
    }
    return undefined
}
