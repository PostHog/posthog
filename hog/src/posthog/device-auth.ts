import { z } from 'zod'

import { PendingApprovalSchema, type PollOutcome } from '@/core/approval'
import { HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import type { Runtime } from '@/core/runtime'
import { parseOrThrow } from '@/core/schema'

import { hostKey, HostSchema, hostUrl, type Host } from './host'
import { ProjectIdSchema, type ProjectId } from './ids'
import { HOG_CLIENT_ID, OAuthErrorBody, OAuthLogin, oauthPost, TokenResponse } from './oauth'
import { stepUpCommand } from './scope-challenge'
import { OAuthRefreshTokenSchema } from './tokens'

const DEVICE_CODE_GRANT = 'urn:ietf:params:oauth:grant-type:device_code'

// What a new login asks for. hog sends this list explicitly, because a request without `scope`
// gets every scope hog's client may hold.
// `workload_trust_policy_request` grants nothing until an admin approves a request in the browser.
const LOGIN_WRITE_SCOPES = [
    'action',
    'alert',
    'annotation',
    'cohort',
    'dashboard',
    'data_catalog',
    'endpoint',
    'error_tracking',
    'event_definition',
    'experiment',
    'external_data_source',
    'feature_flag',
    'heatmap',
    'hog_flow',
    'hog_function',
    'insight',
    'insight_variable',
    'llm_skill',
    'marketing_analytics',
    'notebook',
    'person',
    'product_enablement',
    'project',
    'property_definition',
    'replay_scanner',
    'session_recording_playlist',
    'signal_scout',
    'subscription',
    'survey',
    'task',
    'warehouse_view',
    'workload_trust_policy_request',
]
const LOGIN_READ_SCOPES = [
    'activity_log',
    'batch_export',
    'billing',
    'business_knowledge',
    'dashboard_template',
    'early_access_feature',
    'evaluation',
    'experiment_saved_metric',
    'group',
    'health_issue',
    'integration',
    'llm_prompt',
    'logs',
    'mcp_analytics',
    'organization',
    'organization_member',
    'query',
    'session_recording',
    'ticket',
    'tracing',
    'user',
    'warehouse_table',
    'web_analytics',
]
const LOGIN_IDENTITY_SCOPES = ['openid', 'profile', 'email']
export const LOGIN_SCOPES: readonly string[] = [
    ...LOGIN_IDENTITY_SCOPES,
    ...LOGIN_WRITE_SCOPES.map((object) => `${object}:write`),
    ...LOGIN_READ_SCOPES.map((object) => `${object}:read`),
]

// What `hog auth login --read-only` asks for: the same objects, read access only.
export const READ_ONLY_LOGIN_SCOPES: readonly string[] = [
    ...LOGIN_IDENTITY_SCOPES,
    ...[...LOGIN_WRITE_SCOPES, ...LOGIN_READ_SCOPES].map((object) => `${object}:read`),
]

// A login the person still has to approve in the browser. `deviceCode` redeems the tokens once
// they approve, so it stays in a private file and never reaches the output.
export const PendingLoginSchema = PendingApprovalSchema.extend({
    host: HostSchema,
    deviceCode: z.string(),
    userCode: z.string(),
    scopes: z.array(z.string()),
    requiredScopes: z.array(z.string()).default([]),
    // The project whose login a step-up adds scopes to, which `--wait` can run without naming.
    projectId: ProjectIdSchema.optional(),
})

export type PendingLogin = z.output<typeof PendingLoginSchema>

// PostHog refuses a client it hasn't verified with `unauthorized_client`, and its description says why.
function unauthorizedClient(host: Host, body: OAuthError | undefined): HogError | undefined {
    if (body?.error !== 'unauthorized_client' || body.error_description === undefined) {
        return undefined
    }
    return new HogError(
        'login_unavailable',
        `${host} won't log hog in: ${escapeControls(body.error_description)}`,
        'Set HOG_PERSONAL_API_KEY instead, with the project ID in posthog.json as "projectId" or in HOG_PROJECT_ID.'
    )
}

type OAuthError = z.output<typeof OAuthErrorBody>

// A new login has no earlier refresh token or project to fall back on.
const DeviceTokenResponse = TokenResponse.extend({
    refresh_token: OAuthRefreshTokenSchema,
    scoped_teams: z.tuple([ProjectIdSchema], ProjectIdSchema),
})

const DeviceAuthorizationResponse = z.object({
    device_code: z.string().min(1),
    user_code: z.string().min(1),
    verification_uri: z.string().min(1),
    verification_uri_complete: z.string().optional(),
    expires_in: z.number().positive(),
    interval: z.number().optional(),
})

// hog opens the approval page only on the host it logs in to. A server that names another origin could
// send the person to a look-alike page, and the code check wouldn't catch it: that server chose the code.
function approvalUrl(host: Host, userCode: string, named: string): string {
    if (URL.canParse(named) && new URL(named).origin === hostKey(host)) {
        return named
    }
    const url = hostUrl(host, 'device')
    url.searchParams.set('code', userCode)
    return url.toString()
}

export interface DeviceLoginRequest {
    scopes: readonly string[]
    requiredScopes: readonly string[]
    command: string
    projectId?: ProjectId
}

export async function startDeviceLogin(
    runtime: Runtime,
    host: Host,
    request: DeviceLoginRequest
): Promise<PendingLogin> {
    const { scopes, requiredScopes, command, projectId } = request
    const response = await oauthPost(runtime, host, 'oauth/device-authorization/', {
        client_id: HOG_CLIENT_ID,
        scope: scopes.join(' '),
        ...(requiredScopes.length > 0 ? { required_scopes: requiredScopes.join(' ') } : {}),
    })
    if (response.status === 429) {
        throw new HogError(
            'login_rate_limited',
            `${host} refused to start another login for now.`,
            `Wait a minute, then run \`${command}\` again.`
        )
    }
    const error = OAuthErrorBody.safeParse(response.json).data
    const refused = unauthorizedClient(host, error)
    if (refused) {
        throw refused
    }
    if (error?.error === 'invalid_scope') {
        throw new HogError(
            'invalid_scope',
            `${host} won't give hog these scopes: ${escapeControls(error.error_description ?? 'no reason given')}`,
            'A self-hosted PostHog can be too old for newer scopes. Set HOG_PERSONAL_API_KEY and HOG_PROJECT_ID to use a personal API key instead.'
        )
    }
    const body = response.ok ? DeviceAuthorizationResponse.safeParse(response.json).data : undefined
    if (body === undefined) {
        throw new HogError(
            'login_unavailable',
            `${host} didn't start a login: it answered with HTTP ${response.status}.`,
            'Check the host. A self-hosted PostHog must be able to reach posthog.com to log hog in. Otherwise set HOG_PERSONAL_API_KEY, with the project ID in posthog.json as "projectId" or in HOG_PROJECT_ID.'
        )
    }
    return {
        host,
        deviceCode: body.device_code,
        userCode: body.user_code,
        url: approvalUrl(host, body.user_code, body.verification_uri_complete ?? body.verification_uri),
        expiresAt: runtime.now() + body.expires_in * 1000,
        intervalSeconds: body.interval ?? 5,
        scopes: [...scopes],
        requiredScopes: [...requiredScopes],
        ...(projectId === undefined ? {} : { projectId }),
    }
}

// An older self-hosted PostHog ignores `required_scopes`, so hog checks the approved scopes itself.
async function refuseWithoutRequiredScopes(
    runtime: Runtime,
    login: OAuthLogin,
    requiredScopes: readonly string[]
): Promise<void> {
    if (requiredScopes.length === 0) {
        return
    }
    const { scopesNotCovered } = await import('./scopes')
    const missing = scopesNotCovered(login.scopes, requiredScopes)
    if (missing.length === 0) {
        return
    }
    await login.logout(runtime)
    throw new HogError(
        'scopes_not_granted',
        `The approval didn't include ${missing.join(', ')}, so hog kept your current login.`,
        `Run \`${stepUpCommand(missing, login.host)}\` and keep these scopes when you approve it.`
    )
}

// One poll of the token endpoint, read the way RFC 8628 section 3.5 describes.
export async function pollDeviceLogin(
    runtime: Runtime,
    pending: PendingLogin,
    timeoutMs: number,
    command: string
): Promise<PollOutcome<OAuthLogin>> {
    const response = await oauthPost(
        runtime,
        pending.host,
        'oauth/token/',
        { grant_type: DEVICE_CODE_GRANT, device_code: pending.deviceCode, client_id: HOG_CLIENT_ID },
        timeoutMs
    )
    // A rate limit asks for slower polling, the same as RFC 8628's slow_down.
    if (response.status === 429) {
        return { state: 'slow_down' }
    }
    if (response.status >= 500) {
        return { state: 'retry', reason: `PostHog answered with HTTP ${response.status}.` }
    }
    if (response.ok) {
        const body = parseOrThrow(DeviceTokenResponse, response.json, {
            code: 'unexpected_response',
            context: "PostHog approved the login, but its answer isn't what hog expects.",
            hint: `Run \`${command}\` to start again.`,
        })
        const [projectId] = body.scoped_teams
        const login = OAuthLogin.fromTokens(runtime, body, { host: pending.host, projectId, scopes: pending.scopes })
        await refuseWithoutRequiredScopes(runtime, login, pending.requiredScopes)
        return { state: 'approved', value: login }
    }
    const body = OAuthErrorBody.safeParse(response.json).data
    switch (body?.error) {
        case 'authorization_pending':
            return { state: 'pending' }
        case 'slow_down':
            return { state: 'slow_down' }
        case 'access_denied':
            return { state: 'rejected' }
        case 'expired_token':
            return { state: 'expired' }
    }
    const refused = unauthorizedClient(pending.host, body)
    if (refused) {
        throw refused
    }
    throw new HogError(
        'login_failed',
        `PostHog rejected the login with HTTP ${response.status}.`,
        `Run \`${command}\` to start again.`
    )
}
