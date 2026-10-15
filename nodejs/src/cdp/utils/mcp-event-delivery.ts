import { z } from 'zod'

import type { CyclotronInvocationQueueParametersFetchType } from '~/cdp/schema/cyclotron'
import { parseJSON } from '~/common/utils/json-parse'
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
            return { ok: false, status: 503 }
        }
        return { ok: true, ...parsed.data }
    } catch {
        return { ok: false, status: 503 }
    }
}
