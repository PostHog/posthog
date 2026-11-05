import { createHash, randomUUID } from 'node:crypto'
import { z } from 'zod'

import type { ApiKeyAccess } from '@posthog/mcp/src/cli/library-types'

import { HogError } from '@/core/errors'
import { withFileLock } from '@/core/file-lock'
import type { Runtime } from '@/core/runtime'
import { parseOrThrow, parseOrUndefined } from '@/core/schema'
import type { OAuthSecret, StoreChoice } from '@/posthog/credential-store/types'

import type { AccessKey, AccessKeyStatus, AccessKeyStorage, LogoutOutcome } from './access-key'
import { sendRequest, type HttpResponse } from './api'
import { hostKey, hostUrl, type Host } from './host'
import { ProjectIdSchema, type ProjectId } from './ids'
import type { LoginRecord } from './settings'
import {
    OAuthAccessTokenSchema,
    OAuthRefreshTokenSchema,
    type OAuthAccessToken,
    type OAuthRefreshToken,
} from './tokens'

// hog's CIMD client ID: the URL of its client metadata document, which PostHog fetches.
export const HOG_CLIENT_ID = 'https://posthog.com/.well-known/oauth/hog/client-metadata.json'

const REQUEST_TIMEOUT_MS = 30_000
// Refresh this long before the access token expires, so it doesn't expire during a command.
const REFRESH_MARGIN_MS = 10 * 60_000

export const TokenResponse = z.looseObject({
    access_token: OAuthAccessTokenSchema,
    refresh_token: OAuthRefreshTokenSchema.optional(),
    expires_in: z.number(),
    scope: z.string().optional(),
    scoped_teams: z.array(ProjectIdSchema).optional(),
})

export type TokenResponse = z.output<typeof TokenResponse>

// An RFC 6749 error answer. hog reads `error` only when the answer is one.
export const OAuthErrorBody = z.looseObject({
    error: z.string().optional().catch(undefined),
    error_description: z.string().optional().catch(undefined),
})

export function oauthPost(
    runtime: Runtime,
    host: Host,
    path: string,
    form: Record<string, string>,
    timeoutMs = REQUEST_TIMEOUT_MS
): Promise<HttpResponse> {
    return sendRequest(runtime.fetch, hostUrl(host, path), {
        method: 'POST',
        form,
        timeoutMs,
    })
}

interface OAuthLoginFields {
    host: Host
    projectId: ProjectId
    accessToken: OAuthAccessToken
    refreshToken: OAuthRefreshToken
    // Epoch milliseconds after which the access token stops working.
    expiresAt: number
    scopes: string[]
    // A random id the login keeps for life. The refresh token changes on each renewal, so it can't
    // name the login.
    loginId: string
}

// Serializes the processes that renew or remove the login to one host.
export function withLoginLock<T>(runtime: Runtime, host: Host, work: () => Promise<T>): Promise<T> {
    // By origin, so `https://eu.posthog.com/` and `https://eu.posthog.com` take the same lock.
    const name = createHash('sha256').update(hostKey(host)).digest('hex').slice(0, 16)
    return withFileLock(runtime, `refresh-${name}.lock`, work)
}

// What `hog auth login` gets from the OAuth device grant. The access token works in one project.
export class OAuthLogin implements AccessKey {
    readonly host: Host
    readonly projectId: ProjectId
    readonly accessToken: OAuthAccessToken
    readonly refreshToken: OAuthRefreshToken
    readonly expiresAt: number
    readonly scopes: string[]
    readonly loginId: string

    constructor(fields: OAuthLoginFields) {
        this.host = fields.host
        this.projectId = fields.projectId
        this.accessToken = fields.accessToken
        this.refreshToken = fields.refreshToken
        this.expiresAt = fields.expiresAt
        this.scopes = fields.scopes
        this.loginId = fields.loginId
    }

    // Fields the response leaves out keep this login's values, so a refresh that doesn't rotate the
    // refresh token keeps the old one. A new login gets a new id.
    static fromTokens(
        runtime: Runtime,
        body: TokenResponse,
        previous: Pick<OAuthLoginFields, 'host' | 'projectId' | 'scopes'> & {
            refreshToken?: OAuthRefreshToken
            loginId?: string
        }
    ): OAuthLogin {
        const refreshToken = body.refresh_token ?? previous.refreshToken
        if (refreshToken === undefined) {
            throw new HogError(
                'unexpected_response',
                'PostHog answered without a refresh token.',
                'Run `hog auth login` to log in again.'
            )
        }
        return new OAuthLogin({
            host: previous.host,
            projectId: previous.projectId,
            accessToken: body.access_token,
            refreshToken,
            expiresAt: runtime.now() + body.expires_in * 1000,
            scopes: body.scope ? body.scope.split(' ').filter(Boolean) : previous.scopes,
            loginId: previous.loginId ?? randomUUID(),
        })
    }

    get token(): OAuthAccessToken {
        return this.accessToken
    }

    get loginKey(): string {
        return this.loginId
    }

    private hasTimeLeft(runtime: Runtime): boolean {
        return this.expiresAt - runtime.now() > REFRESH_MARGIN_MS
    }

    // When PostHog rotates refresh tokens, it revokes the whole login if a rotated refresh token is
    // used again, so two hog processes must never refresh at once: the refresh runs under a lock
    // file, and re-reads the stored login inside it to pick up a token another process just stored.
    async fresh(runtime: Runtime, storage: AccessKeyStorage, rejectedToken?: string): Promise<AccessKey> {
        // Another request or process may have renewed the rejected token already, so it only counts
        // while it is still the stored one.
        const needsRenewal = (login: OAuthLogin): boolean =>
            rejectedToken === undefined ? !login.hasTimeLeft(runtime) : login.accessToken === rejectedToken
        if (!needsRenewal(this)) {
            return this
        }
        return withLoginLock(runtime, this.host, async () => {
            const current = await storage.reread()
            if (!(current instanceof OAuthLogin)) {
                throw new HogError(
                    'not_authenticated',
                    'You logged out of hog.',
                    'Run `hog auth login` to log in again.'
                )
            }
            // A new login, possibly to another project, replaced this one. Using it would send the
            // rest of the command to a project it didn't plan against.
            if (current.loginId !== this.loginId) {
                throw new HogError(
                    'login_changed',
                    'You logged in again while this command ran.',
                    'Run the command again to use the new login.'
                )
            }
            if (!needsRenewal(current)) {
                return current
            }
            const renewed = await current.refresh(runtime).catch((error: unknown) => {
                // A lost answer may hide a rotation that already happened. PostHog takes the old
                // refresh token again during its grace period, so one retry recovers the new tokens.
                if (error instanceof HogError && error.code === 'network_error') {
                    return current.refresh(runtime)
                }
                throw error
            })
            try {
                await storage.save(renewed)
            } catch {
                // PostHog already replaced the refresh token, so a lost write ends the login once the
                // grace period passes. One more try covers a keychain that failed for a moment.
                await storage.save(renewed)
            }
            return renewed
        })
    }

    // PostHog issued this login moments ago, so there is nothing to check.
    async verify(): Promise<OAuthLogin> {
        return this
    }

    private async refresh(runtime: Runtime): Promise<OAuthLogin> {
        const response = await oauthPost(runtime, this.host, 'oauth/token/', {
            grant_type: 'refresh_token',
            refresh_token: this.refreshToken,
            client_id: HOG_CLIENT_ID,
        })
        if (response.ok) {
            const body = parseOrThrow(TokenResponse, response.json, {
                code: 'unexpected_response',
                context: "PostHog's answer to the renewal isn't what hog expects.",
                hint: 'Run `hog auth login` to log in again.',
            })
            return OAuthLogin.fromTokens(runtime, body, this)
        }
        if (parseOrUndefined(OAuthErrorBody, response.json)?.error === 'invalid_grant') {
            throw new HogError(
                'session_expired',
                'Your hog login expired or was revoked.',
                'Run `hog auth login` to log in again.'
            )
        }
        throw new HogError(
            'refresh_failed',
            `PostHog didn't renew your login: it answered with HTTP ${response.status}.`,
            'Run the command again. If it keeps failing, run `hog auth login`.'
        )
    }

    status(): AccessKeyStatus {
        return {
            kind: 'oauth',
            scopes: this.scopes,
            expiresAt: this.expiresAt,
            rejected: 'PostHog rejected the token. Someone may have revoked it.',
        }
    }

    // A login works in the one project it was approved for.
    access(): ApiKeyAccess {
        return { scopes: this.scopes, scopedTeams: [Number(this.projectId)], scopedOrganizations: [] }
    }

    // Revoking the refresh token ends this login: PostHog revokes its access tokens with it.
    async logout(runtime: Runtime): Promise<LogoutOutcome> {
        let revoked = false
        try {
            const response = await oauthPost(runtime, this.host, 'oauth/revoke/', {
                token: this.refreshToken,
                token_type_hint: 'refresh_token',
                client_id: HOG_CLIENT_ID,
            })
            revoked = response.ok
        } catch {
            revoked = false
        }
        return { revoked, revokeUrl: null }
    }

    secret(): OAuthSecret {
        return { accessToken: this.accessToken, refreshToken: this.refreshToken }
    }

    record(store: StoreChoice): LoginRecord {
        const { host, projectId, expiresAt, scopes, loginId } = this
        return { store, type: 'oauth', projectId, host, expiresAt, scopes, loginId }
    }
}
