import { HogError } from '@/core/errors'
import type { Runtime } from '@/core/runtime'

import { sendRequest, type HttpResponse } from './api'

// The `agent-cli` use case asks for the scope set the MCP and agent tools need, so a fresh login
// can run any command without authorizing again.
const USE_CASES = 'agent-cli'

const MAX_RETRIES = 3
const REQUEST_TIMEOUT_MS = 30_000
// RFC 8628 asks clients to poll this much slower after each `slow_down`.
const SLOW_DOWN_SECONDS = 5

// A login the person still has to approve in the browser. `deviceCode` retrieves the key once
// they approve, so it stays in a private file and never reaches the output.
export interface PendingLogin {
    host: string
    deviceCode: string
    userCode: string
    url: string
    // Epoch milliseconds after which PostHog forgets the code.
    expiresAt: number
    intervalSeconds: number
}

export interface Approval {
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

// A network failure, a 429 or a 5xx can pass, so the poll retries them. When they don't pass,
// the error is `login_interrupted` and the pending login stays, so `--wait` can resume it.
export async function waitForApproval(runtime: Runtime, pending: PendingLogin): Promise<Approval> {
    let failures = 0
    let intervalSeconds = pending.intervalSeconds
    while (runtime.now() < pending.expiresAt) {
        await runtime.sleep(intervalSeconds * 1000)
        const remaining = pending.expiresAt - runtime.now()
        if (remaining <= 0) {
            break
        }
        let response: HttpResponse
        try {
            response = await post(
                runtime,
                pending.host,
                'poll',
                { device_code: pending.deviceCode },
                Math.min(REQUEST_TIMEOUT_MS, remaining)
            )
        } catch (error) {
            if (++failures > MAX_RETRIES) {
                throw interrupted(error instanceof Error ? error.message : String(error))
            }
            continue
        }
        if (response.status === 429 || response.status >= 500) {
            if (++failures > MAX_RETRIES) {
                throw interrupted(`PostHog answered with HTTP ${response.status}.`)
            }
            intervalSeconds += response.status === 429 ? SLOW_DOWN_SECONDS : 0
            continue
        }
        failures = 0
        if (response.status === 202) {
            continue
        }
        const body = (response.json ?? {}) as PollResponse
        if (response.ok && body.status === 'authorized' && body.personal_api_key && body.project_id !== undefined) {
            return { apiKey: body.personal_api_key, projectId: String(body.project_id), scopes: body.scopes ?? [] }
        }
        if (body.status === 'expired') {
            break
        }
        throw new HogError(
            'login_failed',
            `PostHog rejected the login with HTTP ${response.status}.`,
            'Run `hog auth login` to start again.'
        )
    }
    throw new HogError(
        'login_expired',
        'The login code expired before it was approved.',
        'Run `hog auth login` to get a new code.'
    )
}

function interrupted(reason: string): HogError {
    return new HogError(
        'login_interrupted',
        `hog lost contact with PostHog while waiting for the login: ${reason}`,
        'Run `hog auth login --wait` to keep waiting. The link stays the same.'
    )
}
