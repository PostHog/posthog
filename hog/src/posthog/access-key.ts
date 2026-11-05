import type { ApiKeyAccess } from '@posthog/mcp/src/cli/library-types'

import { HogError } from '@/core/errors'
import type { Runtime } from '@/core/runtime'
import type { StoreChoice, StoredSecret } from '@/posthog/credential-store/types'

import { sendRequest } from './api'
import { hostUrl, type Host } from './host'
import type { ProjectId } from './ids'
import { OAuthLogin } from './oauth'
import type { LoginRecord } from './settings'
import type { BearerToken, PersonalApiKey } from './tokens'

// What `hog auth status` shows about a key.
export interface AccessKeyStatus {
    kind: 'personal_api_key' | 'oauth'
    // Null for a personal API key hog hasn't asked PostHog about.
    scopes: string[] | null
    // Epoch milliseconds. Null for a key that doesn't expire.
    expiresAt: number | null
    // What hog says when PostHog rejects the key.
    rejected: string
}

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
    readonly host: Host
    readonly projectId: ProjectId
    // What PostHog takes as the bearer token.
    readonly token: BearerToken
    // Stays the same for the whole login, unlike an OAuth token, which changes on each renewal.
    readonly loginKey: string
    // A key with time left, renewed if it is about to expire, or if it is still `rejectedToken`,
    // a token PostHog refused.
    fresh(runtime: Runtime, storage: AccessKeyStorage, rejectedToken?: string): Promise<AccessKey>
    // The key as PostHog sees it, before hog stores it. Throws when PostHog rejects it.
    verify(runtime: Runtime): Promise<AccessKey>
    status(): AccessKeyStatus
    // What the key can reach, when hog knows. Null when only PostHog can say.
    access(): ApiKeyAccess | null
    logout(runtime: Runtime): Promise<LogoutOutcome>
    // The credential store keeps the secret, and settings.json keeps the record.
    secret(): StoredSecret
    record(store: StoreChoice): LoginRecord
}

const KEY_CHECK_TIMEOUT_MS = 30_000

export class PersonalAPIKey implements AccessKey {
    readonly host: Host
    readonly projectId: ProjectId
    readonly apiKey: PersonalApiKey
    // Null until `verify` asks PostHog, because only PostHog knows a key's scopes.
    readonly scopes: string[] | null

    constructor(fields: { host: Host; projectId: ProjectId; apiKey: PersonalApiKey; scopes?: string[] }) {
        this.host = fields.host
        this.projectId = fields.projectId
        this.apiKey = fields.apiKey
        this.scopes = fields.scopes ?? null
    }

    get token(): PersonalApiKey {
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
            scopes: this.scopes,
            expiresAt: null,
            rejected: 'PostHog rejected the key. Someone may have deleted it.',
        }
    }

    access(): null {
        return null
    }

    // A key someone deleted, or one pasted only in part, would otherwise fail only at the first
    // command that uses it. A key PostHog just issued already came with its scopes, so it skips the
    // check: its approval is short-lived and a slow check could lose it.
    async verify(runtime: Runtime): Promise<PersonalAPIKey> {
        if (this.scopes !== null) {
            return this
        }
        const response = await sendRequest(runtime.fetch, hostUrl(this.host, 'api/personal_api_keys/@current/'), {
            method: 'GET',
            token: this.apiKey,
            timeoutMs: KEY_CHECK_TIMEOUT_MS,
        })
        if (response.status === 401) {
            throw new HogError(
                'key_rejected',
                `${this.host} rejected the personal API key. The key may belong to another PostHog region or instance, or someone deleted it.`,
                'Check the host, or create a personal API key in PostHog under Settings > Personal API keys and run `hog auth login`.'
            )
        }
        if (!response.ok) {
            throw new HogError(
                'unexpected_response',
                `PostHog answered the key check with HTTP ${response.status}.`,
                'Check the host, then run the command again.'
            )
        }
        const scopes = (response.json as { scopes?: unknown } | undefined)?.scopes
        const { host, projectId, apiKey } = this
        return new PersonalAPIKey({
            host,
            projectId,
            apiKey,
            scopes: Array.isArray(scopes) ? scopes.filter((scope) => typeof scope === 'string') : [],
        })
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
        return { store, type: 'personal_api_key', projectId: this.projectId, host: this.host }
    }
}

// The one place that reads the stored kind. A secret of the wrong kind for its record, such as one
// an older hog wrote, reads as no login.
export function accessKeyFromStorage(record: LoginRecord, secret: StoredSecret): AccessKey | undefined {
    if (record.type === 'personal_api_key' && 'apiKey' in secret) {
        return new PersonalAPIKey({ host: record.host, projectId: record.projectId, apiKey: secret.apiKey })
    }
    if (record.type === 'oauth' && 'accessToken' in secret) {
        const { host, projectId, expiresAt, scopes, loginId } = record
        return new OAuthLogin({ host, projectId, expiresAt, scopes, loginId, ...secret })
    }
    return undefined
}
