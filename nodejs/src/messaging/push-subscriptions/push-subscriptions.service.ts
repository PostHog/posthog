import { createHmac } from 'crypto'
import { LRUCache } from 'lru-cache'

import { EncryptedFields } from '~/cdp/utils/encryption-utils'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { TeamManager } from '~/common/utils/team-manager'

import { verifyPushIdentityToken } from './identity-token'
import { PushCaptureService } from './push-capture'
import { RawRequest, decodeRequest } from './request-decoding'

export type PushRejectionCode =
    | 'method_not_allowed'
    | 'request_too_large'
    | 'invalid_json'
    | 'missing_api_key'
    | 'invalid_api_key'
    | 'missing_fields'
    | 'identity_verification_failed'
    | 'capture_failed'

export type PushErrorType = 'validation_error' | 'authentication_error' | 'server_error'

/** The body shape Django's `generate_exception_response` produces, which SDKs already parse. */
export type PushErrorBody = {
    type: PushErrorType
    code: PushRejectionCode
    detail: string
    attr: null
}

export type PushSuccessBody = {
    distinct_id: string
    stored?: false
    push_enabled?: false
    reason?: string
    detail?: string
}

export type PushHandlerResult = {
    status: number
    body: PushErrorBody | PushSuccessBody
    /** Set on a rejection so the caller can log and count it with the same fields Django uses. */
    rejection?: {
        code: PushRejectionCode
        teamId?: number
        appId?: string | null
        detail?: string
        apiKeyFingerprint?: string
        error?: unknown
    }
    discarded?: { teamId: number; appId: string; reason: 'no_integration' }
    identityVerification?: {
        mode: 'optional' | 'required'
        operation: 'register' | 'unregister'
        outcome: 'verified' | 'unverified'
    }
}

export const MAX_BODY_BYTES = 16 * 1024

const VERIFICATION_MODE_PRECEDENCE: Record<string, number> = { disabled: 0, optional: 1, required: 2 }

type PushIntegration = { config: Record<string, any> }

/** A token this worker resolved to no team recently. Holds a fingerprint, never the raw token.
 *
 * Bounded and in-process rather than in Redis: the token is request-controlled and the endpoint is
 * public, so a shared key per submitted value would let anyone grow the cache and evict real entries.
 * The TTL is short because a token can become valid, for example when a project is recreated.
 */
const INVALID_TOKEN_CACHE_TTL_MS = 60_000
const INVALID_TOKEN_CACHE_SIZE = 2048

/** The app_ids a team has a push channel for. Most registrations name an app_id no team configured,
 * and that path otherwise runs a JSONB filter per request. Keyed on the team alone: the value is a
 * small bounded list, whereas keying on the request's app_id would let one public project token mint
 * unbounded entries.
 *
 * Staleness costs at most one window — a team that configures push keeps discarding for up to a
 * minute — and the device re-posts on its next launch anyway.
 */
const CONFIGURED_APP_IDS_CACHE_TTL_MS = 60_000
const CONFIGURED_APP_IDS_CACHE_SIZE = 10_000

const PUSH_INTEGRATION_KINDS = ['firebase', 'apns']

export type PushRequest = RawRequest

export class PushSubscriptionsService {
    private invalidTokens: LRUCache<string, true>
    private configuredAppIdsCache: LRUCache<number, string[]>

    constructor(
        private teamManager: TeamManager,
        private postgres: PostgresRouter,
        private encryptedFields: EncryptedFields,
        private capture: PushCaptureService,
        private secretKey: string
    ) {
        this.invalidTokens = new LRUCache({ max: INVALID_TOKEN_CACHE_SIZE, ttl: INVALID_TOKEN_CACHE_TTL_MS })
        this.configuredAppIdsCache = new LRUCache({
            max: CONFIGURED_APP_IDS_CACHE_SIZE,
            ttl: CONFIGURED_APP_IDS_CACHE_TTL_MS,
        })
    }

    private apiKeyFingerprint(apiKey: string): string {
        // Keyed with the server secret so a fingerprint cannot be precomputed for a guessed token.
        return createHmac('sha256', this.secretKey).update(apiKey).digest('hex').slice(0, 16)
    }

    public async handle(request: PushRequest): Promise<PushHandlerResult> {
        if (request.method !== 'POST' && request.method !== 'DELETE') {
            return reject('method_not_allowed', 405, 'validation_error', 'Only POST and DELETE requests are supported.')
        }

        if (request.body.length > MAX_BODY_BYTES) {
            return reject('request_too_large', 413, 'validation_error', 'Request body too large.')
        }

        let data: Record<string, any>
        let form: URLSearchParams | undefined
        try {
            const decoded = decodeRequest(request)
            form = decoded.form
            if (typeof decoded.data !== 'object' || decoded.data === null || Array.isArray(decoded.data)) {
                return reject('invalid_json', 400, 'validation_error', 'Invalid JSON body.')
            }
            data = decoded.data as Record<string, any>
        } catch {
            return reject('invalid_json', 400, 'validation_error', 'Invalid JSON body.')
        }

        const apiKey = getToken(data, form)
        if (!apiKey) {
            return reject(
                'missing_api_key',
                401,
                'authentication_error',
                'Project token not provided. You can find your project token in your PostHog project settings.'
            )
        }

        const fingerprint = this.apiKeyFingerprint(apiKey)
        const appIdField = typeof data.app_id === 'string' ? data.app_id : null

        if (this.invalidTokens.has(fingerprint)) {
            return reject('invalid_api_key', 401, 'authentication_error', 'Invalid project token.', {
                appId: appIdField,
                apiKeyFingerprint: fingerprint,
            })
        }

        const team = await this.teamManager.getTeamByToken(apiKey)
        if (!team) {
            this.invalidTokens.set(fingerprint, true)
            return reject('invalid_api_key', 401, 'authentication_error', 'Invalid project token.', {
                appId: appIdField,
                apiKeyFingerprint: fingerprint,
            })
        }

        const missingFields = (['distinct_id', 'device_token', 'app_id'] as const).filter(
            (field) => !data[field] || typeof data[field] !== 'string'
        )
        if (missingFields.length > 0) {
            // absent vs empty vs invalid separates an SDK that never sends the field from a client
            // bridge passing an empty or mistyped value: they need different fixes.
            const detail = missingFields
                .map((field) => {
                    const state = !hasOwn(data, field) ? 'absent' : data[field] === '' ? 'empty' : 'invalid'
                    return `${field}:${state}`
                })
                .join(',')
            return reject(
                'missing_fields',
                400,
                'validation_error',
                `Missing required fields: ${missingFields.join(', ')}.`,
                { teamId: team.id, detail }
            )
        }

        const distinctId = data.distinct_id as string
        const deviceToken = data.device_token as string
        const appId = data.app_id as string

        const integrations = await this.findIntegrations(team.id, appId)

        // A missing integration is an account state, not a request error: SDKs auto-register on every
        // app open, so a 4xx here turns the whole fleet into an error firehose. DELETE falls through,
        // because logout must clear a subscription stored while an integration existed.
        if (integrations.length === 0 && request.method === 'POST') {
            return {
                status: 200,
                body: {
                    distinct_id: distinctId,
                    stored: false,
                    push_enabled: false,
                    // The status code cannot say this: a 4xx would make every SDK retry on every app
                    // open. Without a reason in the body, a developer whose token goes nowhere sees a
                    // success and has no way to tell it from a working registration.
                    reason: 'no_push_channel_for_app_id',
                    detail:
                        `This project has no push channel for app_id '${appId}'. The device token was ` +
                        'not stored. Add a push channel whose Firebase project id or APNs bundle id ' +
                        'matches this app_id, and check the project the SDK is sending to.',
                },
                discarded: { teamId: team.id, appId, reason: 'no_integration' },
            }
        }

        const operation = request.method === 'POST' ? 'register' : 'unregister'
        const verificationMode = strictestVerificationMode(integrations)
        let identityVerification: PushHandlerResult['identityVerification']
        if (verificationMode === 'optional' || verificationMode === 'required') {
            const identityToken = data.identity_token
            const publicKeys = integrations.flatMap(
                (integration) => (integration.config.push_identity_public_keys as string[] | undefined) ?? []
            )
            const verified =
                typeof identityToken === 'string' &&
                verifyPushIdentityToken({
                    token: identityToken,
                    distinctId,
                    appId,
                    publicKeys,
                    secrets: [team.secret_api_token, team.secret_api_token_backup],
                })
            identityVerification = {
                mode: verificationMode,
                operation,
                outcome: verified ? 'verified' : 'unverified',
            }
            if (!verified && verificationMode === 'required') {
                return {
                    ...reject(
                        'identity_verification_failed',
                        401,
                        'authentication_error',
                        'A valid identity token is required for this device. Your backend must sign a ' +
                            'short-lived token for the signed-in user with the key configured for this ' +
                            "channel's identity verification.",
                        { teamId: team.id, appId }
                    ),
                    identityVerification,
                }
            }
        }

        const propertyKey = `$device_push_subscription_${appId}`
        // $unset of an absent property is a no-op, so DELETE is idempotent. device_token is required
        // for a symmetric contract but is not matched against the stored value.
        const properties =
            request.method === 'POST'
                ? { $set: { [propertyKey]: this.encryptedFields.encrypt(deviceToken) } }
                : { $unset: [propertyKey] }

        try {
            // A non-2xx has to surface. An SDK told the registration was stored records it as
            // delivered and stops re-sending it, so a capture that did not happen leaves the device
            // unregistered with nothing reporting it.
            await this.capture.capture({
                token: team.api_token,
                event: '$set',
                distinctId,
                properties: { ...properties, $process_person_profile: true },
            })
        } catch (error) {
            return {
                ...reject(
                    'capture_failed',
                    500,
                    'server_error',
                    request.method === 'POST'
                        ? 'Failed to store push subscription.'
                        : 'Failed to remove push subscription.',
                    { teamId: team.id, appId, error }
                ),
                identityVerification,
            }
        }

        return { status: 200, body: { distinct_id: distinctId }, identityVerification }
    }

    private async findIntegrations(teamId: number, appId: string): Promise<PushIntegration[]> {
        // Skip the JSONB lookup when the team has no channel for this app_id, which is the endpoint's
        // normal case. A failed lookup returns null, meaning "don't know", so the caller falls through
        // to the real query rather than discarding a registration the team is entitled to.
        const configured = await this.configuredAppIds(teamId)
        if (configured !== null && !configured.includes(appId)) {
            return []
        }
        return await this.fetchIntegrations(teamId, appId)
    }

    private async configuredAppIds(teamId: number): Promise<string[] | null> {
        const cached = this.configuredAppIdsCache.get(teamId)
        if (cached) {
            return cached
        }
        try {
            const { rows } = await this.postgres.query<{ kind: string; config: Record<string, any> }>(
                PostgresUse.COMMON_READ,
                `SELECT kind, config FROM posthog_integration WHERE team_id = $1 AND kind = ANY($2)`,
                [teamId, PUSH_INTEGRATION_KINDS],
                'fetchConfiguredPushAppIds'
            )
            const appIds = rows
                .map((row) => (row.kind === 'firebase' ? row.config?.project_id : row.config?.bundle_id))
                .filter((appId): appId is string => typeof appId === 'string')
            this.configuredAppIdsCache.set(teamId, appIds)
            return appIds
        } catch {
            return null
        }
    }

    // Resolved from the app_id alone, not the device platform: an app_id is either a Firebase
    // project_id or an APNs bundle_id, so a device can register with either provider.
    //
    // Read per request rather than cached. The row carries the identity verification policy, so a
    // cached copy would keep answering `disabled` for up to a cache lifetime after an admin turns
    // verification on, and registrations would be stored unverified in that window. The app_id cache
    // above only skips the query for an app_id the team has no channel for at all.
    private async fetchIntegrations(teamId: number, appId: string): Promise<PushIntegration[]> {
        const { rows } = await this.postgres.query<{ config: Record<string, any> }>(
            PostgresUse.COMMON_READ,
            `SELECT config FROM posthog_integration
             WHERE team_id = $1
               AND ((kind = 'firebase' AND config->>'project_id' = $2)
                 OR (kind = 'apns' AND config->>'bundle_id' = $2))`,
            [teamId, appId],
            'fetchPushIntegrations'
        )
        return rows.map((row) => ({ config: row.config ?? {} }))
    }
}

function hasOwn(data: Record<string, any>, field: string): boolean {
    return Object.prototype.hasOwnProperty.call(data, field)
}

function strictestVerificationMode(integrations: PushIntegration[]): string {
    let mode = 'disabled'
    for (const integration of integrations) {
        const candidate = (integration.config.push_identity_verification as string | undefined) ?? 'disabled'
        if ((VERIFICATION_MODE_PRECEDENCE[candidate] ?? 0) > (VERIFICATION_MODE_PRECEDENCE[mode] ?? 0)) {
            mode = candidate
        }
    }
    return mode
}

/** The order Django's `get_token` uses for a body-carrying request. Query parameters are not read:
 * Django only looks at those for GET, and this endpoint takes POST and DELETE. */
function getToken(data: Record<string, any>, form?: URLSearchParams): string | null {
    for (const value of [form?.get('api_key'), form?.get('token')]) {
        if (value) {
            return value
        }
    }
    // Django reads `properties.token` with `.get`, which raises when properties is not a mapping and
    // answers the request with a 500. Treating it as absent answers 401 instead, which is what the
    // client should have been told.
    const properties = typeof data.properties === 'object' && data.properties !== null ? data.properties : {}
    for (const value of [data.$token, data.token, data.api_key, properties.token]) {
        if (typeof value === 'string' && value) {
            return value
        }
    }
    return null
}

function reject(
    code: PushRejectionCode,
    status: number,
    type: PushErrorType,
    detail: string,
    extra: {
        teamId?: number
        appId?: string | null
        detail?: string
        apiKeyFingerprint?: string
        error?: unknown
    } = {}
): PushHandlerResult {
    return {
        status,
        body: { type, code, detail, attr: null },
        rejection: { code, ...extra },
    }
}
