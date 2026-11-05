import { z } from 'zod'

import { PendingApprovalSchema, type PollOutcome } from '@/core/approval'
import { HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import type { Runtime } from '@/core/runtime'

import { hostKey, HostSchema, hostUrl, type Host } from './host'
import { parseProjectId } from './ids'
import { HOG_CLIENT_ID, OAuthLogin, oauthPost, type TokenResponse } from './oauth'

const DEVICE_CODE_GRANT = 'urn:ietf:params:oauth:grant-type:device_code'

// What a new login asks for. hog sends this list explicitly, because a request without `scope`
// gets every scope hog's client may hold.
// TODO: add `ci_trust_policy_request:write` once PostHog has that scope, so `hog ci setup` works
// without a step-up.
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
})

export type PendingLogin = z.output<typeof PendingLoginSchema>

// PostHog refuses a client it hasn't verified with `unauthorized_client`, and its description says why.
function unauthorizedClient(host: Host, body: { error?: string; error_description?: unknown }): HogError | undefined {
    if (body.error !== 'unauthorized_client' || typeof body.error_description !== 'string') {
        return undefined
    }
    return new HogError(
        'login_unavailable',
        `${host} won't log hog in: ${escapeControls(body.error_description)}`,
        'Set HOG_PERSONAL_API_KEY and HOG_PROJECT_ID instead.'
    )
}

interface DeviceAuthorizationResponse {
    device_code?: string
    user_code?: string
    verification_uri?: string
    verification_uri_complete?: string
    expires_in?: number
    interval?: number
}

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

export async function startDeviceLogin(runtime: Runtime, host: Host, scopes: readonly string[]): Promise<PendingLogin> {
    const response = await oauthPost(runtime, host, 'oauth/device-authorization/', {
        client_id: HOG_CLIENT_ID,
        scope: scopes.join(' '),
    })
    if (response.status === 429) {
        throw new HogError(
            'login_rate_limited',
            `${host} refused to start another login for now.`,
            'Wait a minute, then run `hog auth login` again.'
        )
    }
    const body = (response.json ?? {}) as DeviceAuthorizationResponse & { error?: string; error_description?: unknown }
    const refused = unauthorizedClient(host, body)
    if (refused) {
        throw refused
    }
    if (!response.ok || !body.device_code || !body.user_code || !body.verification_uri || !body.expires_in) {
        throw new HogError(
            'login_unavailable',
            `${host} didn't start a login: it answered with HTTP ${response.status}.`,
            'Check the host. A self-hosted PostHog must be able to reach posthog.com to log hog in. Otherwise set HOG_PERSONAL_API_KEY and HOG_PROJECT_ID.'
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
    }
}

// One poll of the token endpoint, read the way RFC 8628 section 3.5 describes.
export async function pollDeviceLogin(
    runtime: Runtime,
    pending: PendingLogin,
    timeoutMs: number
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
    const body = (response.json ?? {}) as TokenResponse & { error?: string; error_description?: unknown }
    if (response.ok) {
        const scopedTeam = body.scoped_teams?.[0]
        if (scopedTeam === undefined || !body.refresh_token) {
            throw new HogError(
                'unexpected_response',
                'PostHog approved the login, but its answer had no project or no refresh token.',
                'Run `hog auth login` to start again.'
            )
        }
        return {
            state: 'approved',
            value: OAuthLogin.fromTokens(runtime, body, {
                host: pending.host,
                projectId: parseProjectId(scopedTeam, {
                    code: 'unexpected_response',
                    hint: 'Run `hog auth login` to start again.',
                }),
                scopes: pending.scopes,
            }),
        }
    }
    switch (body.error) {
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
        'Run `hog auth login` to start again.'
    )
}
