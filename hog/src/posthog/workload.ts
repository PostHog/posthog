import { z } from 'zod'

import type { ApiKeyAccess } from '@posthog/mcp/src/cli/library-types'

import type { WorkloadProvider } from '@/ci/providers/registry'
import { HogError } from '@/core/errors'
import { parseJsonOrUndefined } from '@/core/json'
import type { Runtime } from '@/core/runtime'
import { parseOrThrow } from '@/core/schema'
import type { StoredSecret } from '@/posthog/credential-store/types'

import type { AccessKey, AccessKeyStatus, AccessKeyStorage, LogoutOutcome, WorkloadIdentity } from './access-key'
import type { HttpResponse } from './api'
import { hostUrl, type Host } from './host'
import type { ProjectId } from './ids'
import { grantLifetime, OAuthErrorBody, oauthPost, TokenResponse } from './oauth'
import type { LoginRecord } from './settings'
import { WorkloadTokenSchema, type ProviderIdToken, type WorkloadToken } from './tokens'

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
const MAX_RATE_LIMIT_RETRIES = 3

const SET_HOST =
    'Put the address you open PostHog at in posthog.json as "host", like https://eu.posthog.com, or set HOG_HOST. A self-hosted PostHog needs HOG_HOST. hog asks for an OIDC token for that address and sends it there.'

function exchangeHint(
    code: string,
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
        case 'workload_audience_mismatch':
        case 'workload_invalid_request':
            return SET_HOST
        case 'workload_issuer_not_allowed':
            return `Use HOG_PERSONAL_API_KEY instead, with the project ID in posthog.json or HOG_PROJECT_ID. See ${WORKLOAD_DOCS_URL}`
        case 'workload_exchange_unavailable':
        case 'workload_provider_unavailable':
        case 'workload_rate_limited':
            return 'Run the job again in a minute.'
        default:
            return `See ${WORKLOAD_DOCS_URL}`
    }
}

function exchangeError(status: number, raw: unknown, provider: WorkloadProvider, projectId: ProjectId): HogError {
    const body = ExchangeErrorBody.safeParse(raw).data ?? {}
    const message = body.error_description ?? `PostHog refused the workload token exchange with HTTP ${status}.`
    const code = body.error_code ?? (status >= 500 ? 'workload_exchange_unavailable' : 'workload_exchange_failed')
    const claims = body.claims ? ` The job sent: ${JSON.stringify(body.claims)}.` : ''
    return new HogError(code, `${message}${claims}`, exchangeHint(code, body, provider, projectId))
}

interface WorkloadKeyFields {
    host: Host
    projectId: ProjectId
    provider: WorkloadProvider
    accessToken: WorkloadToken
    // The provider's OIDC token the exchange used. It stays in memory like the access token.
    providerToken: ProviderIdToken
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
    // A large job matrix can use up the repository's exchanges for a moment, so a few short waits save
    // the job. Each wait adds a random part, so the jobs don't all come back in the same second.
    let waited = 0
    for (let attempt = 0; attempt < MAX_RATE_LIMIT_RETRIES && response.status === 429; attempt++) {
        const retryAfter = RetryAfterBody.safeParse(response.json).data?.retry_after
        const wait = retryAfter === undefined ? undefined : retryAfter * (1 + Math.random())
        if (wait === undefined || waited + wait > MAX_RETRY_AFTER_SECONDS) {
            break
        }
        await runtime.sleep(wait * 1000)
        waited += wait
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
        providerToken: subjectToken,
        issuedAt: runtime.now(),
        ...grantLifetime(runtime, body, []),
    })
}

// The token lives a few minutes, so hog keeps it in memory for the run and never stores it.
// PostHog signs the token, and hog reads its payload only to count the workload's runs.
const WorkloadTokenPayload = z.object({
    org_id: z.string().optional().catch(undefined),
    workload: z.object({ provider: z.string(), subject: z.string() }),
})

function workloadIdentity(token: WorkloadToken): WorkloadIdentity | undefined {
    const payload = String(token).split('.')[1]
    const parsed = payload
        ? parseJsonOrUndefined(Buffer.from(payload, 'base64url').toString('utf8'), WorkloadTokenPayload)
        : undefined
    return parsed && { ...parsed.workload, organization: parsed.org_id }
}

class WorkloadKey implements AccessKey {
    readonly host: Host
    readonly projectId: ProjectId
    readonly provider: WorkloadProvider
    readonly accessToken: WorkloadToken
    private readonly providerToken: ProviderIdToken
    readonly issuedAt: number
    readonly expiresAt: number
    readonly scopes: string[]
    readonly identifiesPerson = false
    readonly workload: WorkloadIdentity | undefined
    // Some providers, like GitLab, give a job one OIDC token for the whole run. Once the PostHog token
    // expires with it, another exchange gains nothing, so the key renews only when it has expired.
    private expiresWithProviderToken = false

    constructor(fields: WorkloadKeyFields) {
        this.host = fields.host
        this.projectId = fields.projectId
        this.provider = fields.provider
        this.accessToken = fields.accessToken
        this.providerToken = fields.providerToken
        this.issuedAt = fields.issuedAt
        this.expiresAt = fields.expiresAt
        this.scopes = fields.scopes
        this.workload = workloadIdentity(fields.accessToken)
    }

    get token(): WorkloadToken {
        return this.accessToken
    }

    get loginKey(): string {
        return `workload:${this.provider.key}`
    }

    async fresh(runtime: Runtime, storage: AccessKeyStorage, rejectedToken?: string): Promise<AccessKey> {
        // A short-lived token renews at half its life, so it isn't exchanged on every request.
        const margin = this.expiresWithProviderToken
            ? 0
            : Math.min(RENEW_MARGIN_MS, (this.expiresAt - this.issuedAt) / 2)
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
        renewed.expiresWithProviderToken = renewed.providerToken === this.providerToken
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
            fix: 'hog ci setup',
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
