import { z } from 'zod'

import type { CyclotronInvocationQueueParametersFetchType } from '~/cdp/schema/cyclotron'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { internalFetch } from '~/common/utils/request'

import type { CyclotronJobInvocationHogFunction } from '../types'
import { resolveHogFunctionInputValue } from './hog-function-inputs'

const DeliveryResponse = z.object({
    body: z.string(),
    headers: z.record(z.string(), z.string()),
})

export type McpEventDeliveryResult =
    | { ok: true; body: string; headers: Record<string, string> }
    | { ok: false; status: number; retryAfterMs?: number }

type AuthorizationFailureCategory = 'dns' | 'connection' | 'timeout' | 'network' | 'invalid_response'

function authorizationFailureCategory(error: unknown): AuthorizationFailureCategory {
    const cause = error instanceof Error && error.cause ? error.cause : error
    const code = (cause as { code?: unknown } | null)?.code
    const name = (cause as { name?: unknown } | null)?.name
    if (name === 'SyntaxError') {
        return 'invalid_response'
    }
    if (
        name === 'TimeoutError' ||
        name === 'AbortError' ||
        [
            'ETIMEDOUT',
            'ABORT_ERR',
            'UND_ERR_CONNECT_TIMEOUT',
            'UND_ERR_HEADERS_TIMEOUT',
            'UND_ERR_BODY_TIMEOUT',
        ].includes(typeof code === 'string' ? code : '')
    ) {
        return 'timeout'
    }
    if (code === 'ENOTFOUND' || code === 'EAI_AGAIN') {
        return 'dns'
    }
    if (['ECONNREFUSED', 'ECONNRESET', 'EPIPE', 'UND_ERR_SOCKET'].includes(typeof code === 'string' ? code : '')) {
        return 'connection'
    }
    return 'network'
}

export async function prepareMcpEventDelivery({
    invocation,
    params,
    internalApiBaseUrl,
}: {
    invocation: CyclotronJobInvocationHogFunction
    params: CyclotronInvocationQueueParametersFetchType
    internalApiBaseUrl: string
}): Promise<McpEventDeliveryResult> {
    const subscription = params.mcp_event_subscription
    const logFailure = (category: AuthorizationFailureCategory | 'http_error', status?: number): void => {
        logger.warn('[MCP event delivery] Authorization request failed', {
            invocationId: invocation.id,
            teamId: invocation.teamId,
            hogFunctionId: invocation.hogFunction.id,
            subscriptionId: subscription?.id,
            category,
            status,
        })
    }
    const credential = resolveHogFunctionInputValue(invocation.hogFunction, 'mcp_credential')
    if (!subscription || typeof credential !== 'string' || !credential) {
        return { ok: false, status: 403 }
    }

    // Reuse the caller's credential so Django enforces current scopes and membership on every attempt.
    try {
        const response = await internalFetch(
            `${internalApiBaseUrl}/api/projects/${invocation.teamId}/mcp_event_subscriptions/${subscription.id}/authorize_delivery/`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${credential}` },
                body: JSON.stringify({
                    generation: subscription.generation,
                    filter_bytecode: subscription.filter_bytecode,
                    function_id: invocation.hogFunction.id,
                    url: params.url,
                    body: params.body,
                }),
                timeoutMs: 10_000,
            }
        )
        if (response.status !== 200) {
            logFailure('http_error', response.status)
            const retryAfter = response.headers?.['retry-after']
            const rawRetryAfter = Array.isArray(retryAfter) ? retryAfter[0] : retryAfter
            const parsedDelay = rawRetryAfter
                ? /^\d+(\.\d+)?$/.test(rawRetryAfter)
                    ? Number(rawRetryAfter) * 1000
                    : Date.parse(rawRetryAfter) - Date.now()
                : NaN
            const retryAfterMs = Number.isFinite(parsedDelay) ? Math.max(0, parsedDelay) : undefined
            await response.dump()
            return {
                ok: false,
                ...(retryAfterMs !== undefined ? { retryAfterMs } : {}),
                status: [401, 403, 404].includes(response.status)
                    ? 410
                    : response.status >= 500 || response.status === 429
                      ? 503
                      : response.status,
            }
        }
        const parsed = DeliveryResponse.safeParse(parseJSON(await response.text()))
        if (!parsed.success) {
            logFailure('invalid_response', response.status)
            return { ok: false, status: 503 }
        }
        return { ok: true, ...parsed.data }
    } catch (error) {
        logFailure(authorizationFailureCategory(error))
        return { ok: false, status: 503 }
    }
}
