import { z } from 'zod'

import type { CyclotronInvocationQueueParametersMcpEventType } from '~/cdp/schema/cyclotron'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { internalFetch } from '~/common/utils/request'

import type { CyclotronJobInvocationHogFunction } from '../types'
import { isFetchResponseRetriable } from './cdp-fetch'
import { resolveHogFunctionInputValue } from './hog-function-inputs'

const DeliveryResponse = z.object({
    body: z.string(),
    headers: z.record(z.string(), z.string()),
})

export type McpEventDeliveryResult =
    | { ok: true; body: string; headers: Record<string, string> }
    | { ok: false; retryable: boolean; retryAfterMs?: number }

export type McpEventDeliveryFailureCategory = 'dns' | 'connection' | 'timeout' | 'network' | 'invalid_response'

export function mcpEventDeliveryFailureCategory(error: unknown): McpEventDeliveryFailureCategory {
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

export function parseRetryAfterMs(header: string | string[] | undefined): number | undefined {
    const raw = Array.isArray(header) ? header[0] : header
    if (!raw) {
        return undefined
    }
    const delay = /^\d+(\.\d+)?$/.test(raw) ? Number(raw) * 1000 : Date.parse(raw) - Date.now()
    const boundedDelay = Math.max(0, delay)
    return Number.isFinite(new Date(Date.now() + boundedDelay).getTime()) ? boundedDelay : undefined
}

export async function prepareMcpEventDelivery({
    invocation,
    params,
    internalApiBaseUrl,
}: {
    invocation: CyclotronJobInvocationHogFunction
    params: CyclotronInvocationQueueParametersMcpEventType
    internalApiBaseUrl: string
}): Promise<McpEventDeliveryResult> {
    const subscription = params.mcp_event_subscription
    const logFailure = (category: McpEventDeliveryFailureCategory | 'http_error', status?: number): void => {
        logger.warn('[MCP event delivery] Authorization request failed', {
            invocationId: invocation.id,
            teamId: invocation.teamId,
            hogFunctionId: invocation.hogFunction.id,
            subscriptionId: subscription.id,
            category,
            status,
        })
    }
    const credential = resolveHogFunctionInputValue(invocation.hogFunction, 'mcp_credential')
    const matchedFilter = invocation.state.mcpEvent?.filterBytecode
    if (typeof credential !== 'string' || !credential || !Array.isArray(matchedFilter)) {
        return { ok: false, retryable: false }
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
                    filter_bytecode: matchedFilter,
                    function_id: invocation.hogFunction.id,
                    url: params.url,
                    body: params.body,
                }),
                timeoutMs: 10_000,
            }
        )
        if (response.status !== 200) {
            logFailure('http_error', response.status)
            const retryAfterMs = parseRetryAfterMs(response.headers?.['retry-after'])
            await response.dump()
            return {
                ok: false,
                ...(retryAfterMs !== undefined ? { retryAfterMs } : {}),
                retryable: isFetchResponseRetriable(response, null),
            }
        }
        const parsed = DeliveryResponse.safeParse(parseJSON(await response.text()))
        if (!parsed.success) {
            logFailure('invalid_response', response.status)
            return { ok: false, retryable: true }
        }
        return { ok: true, ...parsed.data }
    } catch (error) {
        logFailure(mcpEventDeliveryFailureCategory(error))
        return { ok: false, retryable: true }
    }
}
