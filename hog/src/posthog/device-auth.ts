import type { PendingApproval, PollOutcome } from '@/core/approval'
import { HogError } from '@/core/errors'
import type { Runtime } from '@/core/runtime'

import { sendRequest, type HttpResponse } from './api'

// The `agent-cli` use case asks for the scope set the MCP and agent tools need, so a fresh login
// can run any command without authorizing again.
const USE_CASES = 'agent-cli'

const REQUEST_TIMEOUT_MS = 30_000

// A login the person still has to approve in the browser. `deviceCode` retrieves the key once
// they approve, so it stays in a private file and never reaches the output.
export interface PendingLogin extends PendingApproval {
    host: string
    deviceCode: string
    userCode: string
}

export interface Approval {
    host: string
    apiKey: string
    projectId: string
    scopes: string[]
}

interface DeviceCodeResponse {
    device_code: string
    user_code: string
    verification_uri_complete: string
    expires_in: number
    interval: number
}

interface PollResponse {
    status?: 'pending' | 'authorized' | 'expired'
    personal_api_key?: string
    project_id?: string | number
    scopes?: string[]
}

function post(runtime: Runtime, host: string, path: string, body: unknown, timeoutMs: number): Promise<HttpResponse> {
    return sendRequest(runtime.fetch, new URL(`api/cli-auth/${path}/`, host), { method: 'POST', body, timeoutMs })
}

export async function startDeviceLogin(runtime: Runtime, host: string): Promise<PendingLogin> {
    const response = await post(runtime, host, 'device-code', undefined, REQUEST_TIMEOUT_MS)
    const body = response.json as DeviceCodeResponse | undefined
    if (!response.ok || !body?.device_code) {
        throw new HogError(
            'login_unavailable',
            `${host} didn't start a login: it answered with HTTP ${response.status}.`,
            'Check the host. Self-hosted PostHog needs a version that supports CLI login.'
        )
    }
    const url = new URL(body.verification_uri_complete)
    url.searchParams.set('use_cases', USE_CASES)
    return {
        host,
        deviceCode: body.device_code,
        userCode: body.user_code,
        url: url.toString(),
        expiresAt: runtime.now() + body.expires_in * 1000,
        intervalSeconds: body.interval,
    }
}

export async function pollDeviceLogin(
    runtime: Runtime,
    pending: PendingLogin,
    timeoutMs: number
): Promise<PollOutcome<Approval>> {
    const response = await post(runtime, pending.host, 'poll', { device_code: pending.deviceCode }, timeoutMs)
    if (response.status === 429) {
        return { state: 'slow_down' }
    }
    if (response.status >= 500) {
        return { state: 'retry', reason: `PostHog answered with HTTP ${response.status}.` }
    }
    if (response.status === 202) {
        return { state: 'pending' }
    }
    const body = (response.json ?? {}) as PollResponse
    if (response.ok && body.status === 'authorized' && body.personal_api_key && body.project_id !== undefined) {
        return {
            state: 'approved',
            value: {
                host: pending.host,
                apiKey: body.personal_api_key,
                projectId: String(body.project_id),
                scopes: body.scopes ?? [],
            },
        }
    }
    if (body.status === 'expired') {
        return { state: 'expired' }
    }
    throw new HogError(
        'login_failed',
        `PostHog rejected the login with HTTP ${response.status}.`,
        'Run `hog auth login` to start again.'
    )
}
