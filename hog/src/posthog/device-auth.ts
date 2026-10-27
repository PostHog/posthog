import { HogError } from '@/core/errors'
import type { Runtime } from '@/core/runtime'

import { USER_AGENT } from './api'

// The `agent-cli` use case asks for the scope set the MCP and agent tools need, so a fresh login
// can run any command without authorizing again.
const USE_CASES = 'agent-cli'

const MAX_NETWORK_RETRIES = 3

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

async function post(runtime: Runtime, host: string, path: string, body?: unknown): Promise<Response> {
    try {
        return await runtime.fetch(new URL(`api/cli-auth/${path}/`, host), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'User-Agent': USER_AGENT },
            body: body === undefined ? undefined : JSON.stringify(body),
        })
    } catch (error) {
        throw new HogError(
            'network_error',
            `hog couldn't reach ${host}: ${error instanceof Error ? error.message : String(error)}`,
            'Check the host and your network connection.'
        )
    }
}

export async function startDeviceLogin(runtime: Runtime, host: string): Promise<PendingLogin> {
    const response = await post(runtime, host, 'device-code')
    if (!response.ok) {
        throw new HogError(
            'login_unavailable',
            `${host} didn't start a login: it answered with HTTP ${response.status}.`,
            'Check the host. Self-hosted PostHog needs a version that supports CLI login.'
        )
    }
    const body = (await response.json()) as {
        device_code: string
        user_code: string
        verification_uri_complete: string
        expires_in: number
        interval: number
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

export async function waitForApproval(runtime: Runtime, pending: PendingLogin): Promise<Approval> {
    let failures = 0
    while (runtime.now() < pending.expiresAt) {
        await runtime.sleep(pending.intervalSeconds * 1000)
        let response: Response
        try {
            response = await post(runtime, pending.host, 'poll', { device_code: pending.deviceCode })
            failures = 0
        } catch (error) {
            if (++failures > MAX_NETWORK_RETRIES) {
                throw error
            }
            continue
        }
        if (response.status === 202) {
            continue
        }
        const body = (await response.json().catch(() => ({}))) as {
            status?: string
            personal_api_key?: string
            project_id?: string | number
            scopes?: string[]
        }
        if (response.ok && body.status === 'authorized' && body.personal_api_key && body.project_id !== undefined) {
            return { apiKey: body.personal_api_key, projectId: String(body.project_id), scopes: body.scopes ?? [] }
        }
        if (body.status === 'expired') {
            break
        }
        throw new HogError(
            'login_failed',
            `PostHog rejected the login with HTTP ${response.status}.`,
            'Run `hog login` to start again.'
        )
    }
    throw new HogError(
        'login_expired',
        'The login code expired before it was approved.',
        'Run `hog login` to get a new code.'
    )
}
