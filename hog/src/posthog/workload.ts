import { z } from 'zod'

import type { ApiKeyAccess } from '@posthog/mcp/src/cli/library-types'

import type { WorkloadProvider } from '@/ci/providers'
import { HogError } from '@/core/errors'
import type { Runtime } from '@/core/runtime'
import { parseOrThrow } from '@/core/schema'
import type { StoredSecret } from '@/posthog/credential-store/types'

import type { AccessKey, AccessKeyStatus, AccessKeyStorage, LogoutOutcome } from './access-key'
import type { HttpResponse } from './api'
import { hostUrl, type Host } from './host'
import type { ProjectId } from './ids'
import { grantLifetime, OAuthErrorBody, oauthPost, TokenResponse } from './oauth'
import type { LoginRecord } from './settings'
import { WorkloadTokenSchema, type WorkloadToken } from './tokens'

const TOKEN_EXCHANGE_GRANT_TYPE = 'urn:ietf:params:oauth:grant-type:token-exchange'
const ID_TOKEN_TYPE = 'urn:ietf:params:oauth:token-type:id_token'
// The workload token never outlives the provider's, which can live five minutes, so renew early.
const RENEW_MARGIN_MS = 60_000
const WORKLOAD_DOCS_URL = 'https://posthog.com/docs/api/workload-identity'

const ExchangeResponse = TokenResponse.pick({ expires_in: true, scope: true }).extend({
    access_token: WorkloadTokenSchema,
})

const ExchangeErrorBody = OAuthErrorBody.extend({
    error_code: z.string().optional().catch(undefined),
    approval_url: z.string().optional().catch(undefined),
    claims: z.record(z.string(), z.unknown()).optional().catch(undefined),
})

const RetryAfterBody = z.object({ retry_after: z.number().int().nonnegative() })
const MAX_RETRY_AFTER_SECONDS = 60

const TRY_AGAIN = 'Run the job again in a minute.'
const SET_HOST =
    'Set HOG_HOST to the address you open PostHog at, like https://us.posthog.com. hog asks for an OIDC token for that address and sends it there.'
const NEXT_STEP: Record<string, string> = {
    workload_invalid_request: SET_HOST,
    workload_exchange_unavailable: TRY_AGAIN,
    workload_issuer_not_allowed: `Use HOG_PERSONAL_API_KEY and HOG_PROJECT_ID instead. See ${WORKLOAD_DOCS_URL}`,
    workload_provider_unavailable: TRY_AGAIN,
    workload_rate_limited: TRY_AGAIN,
}

function exchangeHint(
    code: string,
    message: string,
    body: z.output<typeof ExchangeErrorBody>,
    provider: WorkloadProvider,
    projectId: ProjectId
): string {
    switch (code) {
        case 'workload_no_matching_policy':
            return `Run \`hog ci setup\` on your machine to ask an admin to trust this ${provider.name} workload in project ${projectId}.`
        case 'workload_policy_request_pending':
            return body.approval_url
                ? `Ask an organization admin to approve the request: ${body.approval_url}`
                : 'Ask an organization admin to approve the request in PostHog.'
        case 'workload_token_invalid':
            if (message.includes('audience')) {
                return SET_HOST
            }
    }
    return NEXT_STEP[code] ?? `See ${WORKLOAD_DOCS_URL}`
}

function exchangeError(status: number, raw: unknown, provider: WorkloadProvider, projectId: ProjectId): HogError {
    const body = ExchangeErrorBody.safeParse(raw).data ?? {}
    const message = body.error_description ?? `PostHog refused the workload token exchange with HTTP ${status}.`
    const code = body.error_code ?? (status >= 500 ? 'workload_exchange_unavailable' : 'workload_exchange_failed')
    const claims = body.claims ? ` The job sent: ${JSON.stringify(body.claims)}.` : ''
    return new HogError(code, `${message}${claims}`, exchangeHint(code, message, body, provider, projectId))
}

interface WorkloadKeyFields {
    host: Host
    projectId: ProjectId
    provider: WorkloadProvider
    accessToken: WorkloadToken
    // Epoch milliseconds when PostHog issued the token, and after which it refuses it.
    issuedAt: number
    expiresAt: number
    scopes: string[]
}

export async function exchangeWorkloadToken(
    runtime: Runtime,
    fields: Pick<WorkloadKeyFields, 'host' | 'projectId' | 'provider'>
): Promise<WorkloadKey | undefined> {
    const { host, projectId, provider } = fields
    const subjectToken = await provider.fetchToken(runtime, host)
    if (subjectToken === undefined) {
        return undefined
    }
    const exchange = (): Promise<HttpResponse> =>
        oauthPost(runtime, host, 'oauth/token/', {
            grant_type: TOKEN_EXCHANGE_GRANT_TYPE,
            subject_token: subjectToken,
            subject_token_type: ID_TOKEN_TYPE,
            resource: hostUrl(host, `api/projects/${projectId}`).toString(),
        })
    let response = await exchange()
    // A large job matrix can use up the repository's exchanges for a moment, so one short wait saves the job.
    const retryAfter = RetryAfterBody.safeParse(response.json).data?.retry_after
    if (response.status === 429 && retryAfter !== undefined && retryAfter <= MAX_RETRY_AFTER_SECONDS) {
        await runtime.sleep(retryAfter * 1000)
        response = await exchange()
    }
    if (!response.ok) {
        throw exchangeError(response.status, response.json, provider, projectId)
    }
    const body = parseOrThrow(ExchangeResponse, response.json, {
        code: 'unexpected_response',
        context: "PostHog's answer to the workload token exchange isn't what hog expects.",
        hint: 'Check that the host runs a recent version of PostHog.',
    })
    return new WorkloadKey({
        host,
        projectId,
        provider,
        accessToken: body.access_token,
        issuedAt: runtime.now(),
        ...grantLifetime(runtime, body, []),
    })
}

// The token lives a few minutes, so hog keeps it in memory for the run and never stores it.
export class WorkloadKey implements AccessKey {
    readonly host: Host
    readonly projectId: ProjectId
    readonly provider: WorkloadProvider
    readonly accessToken: WorkloadToken
    readonly issuedAt: number
    readonly expiresAt: number
    readonly scopes: string[]
    readonly identifiesPerson = false

    constructor(fields: WorkloadKeyFields) {
        this.host = fields.host
        this.projectId = fields.projectId
        this.provider = fields.provider
        this.accessToken = fields.accessToken
        this.issuedAt = fields.issuedAt
        this.expiresAt = fields.expiresAt
        this.scopes = fields.scopes
    }

    get token(): WorkloadToken {
        return this.accessToken
    }

    get loginKey(): string {
        return `workload:${this.provider.key}`
    }

    async fresh(runtime: Runtime, storage: AccessKeyStorage, rejectedToken?: string): Promise<AccessKey> {
        // A short-lived token renews at half its life, so it isn't exchanged on every request.
        const margin = Math.min(RENEW_MARGIN_MS, (this.expiresAt - this.issuedAt) / 2)
        const needsRenewal =
            rejectedToken === undefined ? this.expiresAt - runtime.now() <= margin : this.accessToken === rejectedToken
        if (!needsRenewal) {
            return this
        }
        const renewed = await exchangeWorkloadToken(runtime, this)
        if (renewed === undefined) {
            throw new HogError(
                'workload_token_unavailable',
                `${this.provider.name} stopped issuing OIDC tokens to this job.`,
                this.provider.missingTokenHint
            )
        }
        await storage.save(renewed)
        return renewed
    }

    async verify(): Promise<WorkloadKey> {
        return this
    }

    status(): AccessKeyStatus {
        return {
            kind: 'workload',
            scopes: this.scopes,
            expiresAt: this.expiresAt,
            rejected: `PostHog rejected the workload token. An admin may have disabled or deleted the trust policy for this ${this.provider.name} workload.`,
            provider: this.provider.name,
        }
    }

    access(): ApiKeyAccess {
        return { scopes: this.scopes, scopedTeams: [Number(this.projectId)], scopedOrganizations: [] }
    }

    async logout(): Promise<LogoutOutcome> {
        return { revoked: null, revokeUrl: null }
    }

    secret(): StoredSecret {
        throw notStored()
    }

    record(): LoginRecord {
        throw notStored()
    }
}

function notStored(): HogError {
    return new HogError('workload_not_stored', 'hog never stores a workload token.')
}
