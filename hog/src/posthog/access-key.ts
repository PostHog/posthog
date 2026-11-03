import type { ApiKeyAccess } from '@posthog/mcp/src/cli/library-types'

import type { Runtime, RuntimeFetch } from '@/core/runtime'

import { ApiError, PostHogApi } from './api'
import type { StoreChoice, StoredSecret } from './credential-store/types'
import { hostUrl } from './host'
import { OAuthLogin } from './oauth'
import type { LoginRecord } from './settings'

// What `hog auth status` shows about a key.
export interface AccessKeyStatus {
    kind: 'personal_api_key' | 'oauth'
    // Null for a personal API key, whose scopes only PostHog knows.
    scopes: string[] | null
    // Epoch milliseconds. Null for a key that doesn't expire.
    expiresAt: number | null
    // What hog says when PostHog rejects the key.
    rejected: string
}

// What logging out did in PostHog.
export interface LogoutOutcome {
    // Whether PostHog revoked the login. Null for a key hog can't revoke.
    revoked: boolean | null
    // Where to delete a key that keeps working after logout.
    revokeUrl: string | null
}

// How a stored key reaches its stored copy, so a renewal can read the latest one and save the new one.
export interface AccessKeyStorage {
    reread(): Promise<AccessKey | undefined>
    save(key: AccessKey): Promise<void>
}

// A key hog sends to PostHog. Each kind owns how it authenticates, renews, logs out and is stored,
// so callers never branch on the kind.
export interface AccessKey {
    readonly host: string
    readonly projectId: string
    // What PostHog takes as the bearer token.
    readonly token: string
    // Stays the same for the whole login, unlike an OAuth token, which changes on each renewal.
    readonly loginKey: string
    // A key that works for the rest of the command, renewed if it is about to expire.
    fresh(runtime: Runtime, storage: AccessKeyStorage): Promise<AccessKey>
    status(): AccessKeyStatus
    // What the key can reach, when hog knows. Null when only PostHog can say.
    access(): ApiKeyAccess | null
    logout(runtime: Runtime): Promise<LogoutOutcome>
    // The credential store keeps the secret, and settings.json keeps the record.
    secret(): StoredSecret
    record(store: StoreChoice): LoginRecord
}

export class PersonalAPIKey implements AccessKey {
    readonly host: string
    readonly projectId: string
    readonly apiKey: string

    constructor(fields: { host: string; projectId: string; apiKey: string }) {
        this.host = fields.host
        this.projectId = fields.projectId
        this.apiKey = fields.apiKey
    }

    get token(): string {
        return this.apiKey
    }

    get loginKey(): string {
        return this.apiKey
    }

    async fresh(): Promise<AccessKey> {
        return this
    }

    status(): AccessKeyStatus {
        return {
            kind: 'personal_api_key',
            scopes: null,
            expiresAt: null,
            rejected: 'PostHog rejected the key. Someone may have deleted it.',
        }
    }

    access(): null {
        return null
    }

    // What PostHog knows about the key. Undefined when PostHog rejects it, such as after someone
    // deleted it.
    async lookup(fetchFn: RuntimeFetch): Promise<{ scopes: string[] } | undefined> {
        try {
            const found = await new PostHogApi(this, fetchFn).get<{ scopes?: string[] }>(
                '/api/personal_api_keys/@current/'
            )
            return { scopes: found.scopes ?? [] }
        } catch (error) {
            if (error instanceof ApiError && error.status === 401) {
                return undefined
            }
            throw error
        }
    }

    // A personal API key can't be revoked from hog, so logout says where to delete it.
    async logout(): Promise<LogoutOutcome> {
        return {
            revoked: null,
            revokeUrl: hostUrl(this.host, 'settings/user-api-keys').toString(),
        }
    }

    secret(): StoredSecret {
        return { apiKey: this.apiKey }
    }

    record(store: StoreChoice): LoginRecord {
        return { store, type: 'personal_api_key', projectId: this.projectId }
    }
}

// The one place that reads the stored kind. A secret of the wrong kind for its record, such as one
// an older hog wrote, reads as no login.
export function accessKeyFromStorage(host: string, record: LoginRecord, secret: StoredSecret): AccessKey | undefined {
    if (record.type === 'personal_api_key' && 'apiKey' in secret) {
        return new PersonalAPIKey({ host, projectId: record.projectId, apiKey: secret.apiKey })
    }
    if (record.type === 'oauth' && 'accessToken' in secret) {
        const { projectId, expiresAt, scopes, loginId } = record
        return new OAuthLogin({ host, projectId, expiresAt, scopes, loginId, ...secret })
    }
    return undefined
}
