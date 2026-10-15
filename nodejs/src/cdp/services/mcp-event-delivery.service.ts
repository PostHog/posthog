import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersMcpEventSchema } from '~/cdp/schema/cyclotron'
import { logger } from '~/common/utils/logger'

import type { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { createAddLogFunction } from '../utils'
import { cdpTrackedFetch, isFetchResponseRetriable } from '../utils/cdp-fetch'
import { createInvocationResult } from '../utils/invocation-utils'
import {
    type McpEventDeliveryFailureCategory,
    mcpEventDeliveryFailureCategory,
    parseRetryAfterMs,
    prepareMcpEventDelivery,
} from '../utils/mcp-event-delivery'

type DeliveryAttempt =
    | { ok: true; status: number }
    | {
          ok: false
          retryable: boolean
          retryAfterMs?: number
          callback?: { category: McpEventDeliveryFailureCategory | 'http_error'; status?: number }
      }

export async function executeMcpEventDelivery(
    invocation: CyclotronJobInvocationHogFunction,
    config: { internalApiBaseUrl: string; fetchRetries: number; fetchBackoffBaseMs: number; fetchBackoffMaxMs: number }
): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
    const result = createInvocationResult<CyclotronJobInvocationHogFunction>(invocation, {}, { finished: false })
    const addLog = createAddLogFunction(result.logs)
    const parsed = CyclotronInvocationQueueParametersMcpEventSchema.safeParse(invocation.queueParameters)
    if (!parsed.success) {
        result.error = new Error('Invalid MCP event delivery parameters.')
        result.finished = true
        return result
    }

    const params = parsed.data
    const started = performance.now()
    let attempt: DeliveryAttempt
    try {
        const prepared = await prepareMcpEventDelivery({
            invocation,
            params,
            internalApiBaseUrl: config.internalApiBaseUrl,
        })
        if (!prepared.ok) {
            attempt = prepared
        } else {
            const { fetchError, fetchResponse } = await cdpTrackedFetch({
                url: params.url,
                fetchParams: { method: 'POST', body: prepared.body, headers: prepared.headers },
                templateId: 'mcp-event-subscription',
                teamId: invocation.teamId,
                hogFunctionId: invocation.hogFunction.id,
                retryConnectionErrors: false,
            })
            const retryAfterMs = parseRetryAfterMs(fetchResponse?.headers['retry-after'])
            // The managed program ignores callback bodies; acknowledgement depends on the status.
            await fetchResponse?.dump().catch(() => {})
            attempt =
                fetchResponse && fetchResponse.status >= 200 && fetchResponse.status < 300
                    ? { ok: true, status: fetchResponse.status }
                    : {
                          ok: false,
                          retryable: isFetchResponseRetriable(fetchResponse, fetchError),
                          retryAfterMs,
                          callback: {
                              category: fetchResponse ? 'http_error' : mcpEventDeliveryFailureCategory(fetchError),
                              status: fetchResponse?.status,
                          },
                      }
        }
    } catch (error) {
        attempt = { ok: false, retryable: isFetchResponseRetriable(null, error) }
    } finally {
        result.invocation.state.timings.push({ kind: 'async_function', duration_ms: performance.now() - started })
    }

    result.invocation.state.attempts++
    if (!attempt.ok) {
        const willRetry = attempt.retryable && result.invocation.state.attempts < config.fetchRetries
        const detail = attempt.callback
            ? ` (callback ${attempt.callback.status !== undefined ? `HTTP ${attempt.callback.status}` : attempt.callback.category})`
            : ''
        addLog('error', `MCP event delivery failed${detail}.${willRetry ? ' Retrying.' : ''}`)
        if (attempt.callback) {
            logger.warn('[MCP event delivery] Callback request failed', {
                invocationId: invocation.id,
                teamId: invocation.teamId,
                hogFunctionId: invocation.hogFunction.id,
                subscriptionId: params.mcp_event_subscription.id,
                ...attempt.callback,
            })
        }
        if (willRetry) {
            const backoffMs = Math.min(
                config.fetchBackoffBaseMs * 2 ** (result.invocation.state.attempts - 1),
                config.fetchBackoffMaxMs
            )
            result.invocation.queueParameters = params
            result.invocation.queuePriority = invocation.queuePriority + 1
            const scheduledAt = DateTime.utc().plus({
                milliseconds: Math.max(backoffMs, attempt.retryAfterMs ?? 0),
            })
            result.invocation.queueScheduledAt = scheduledAt.isValid
                ? scheduledAt
                : DateTime.utc().plus({ milliseconds: backoffMs })
            return result
        }
        result.error = new Error('MCP event delivery failed.')
        result.finished = true
    } else {
        result.invocation.state.attempts = 0
        const response = { status: attempt.status, body: {} }
        result.invocation.state.vmState!.stack.push(response)
        result.execResult = response
    }

    result.metrics.push({
        team_id: invocation.teamId,
        app_source_id: invocation.parentRunId ?? invocation.functionId,
        metric_kind: 'other',
        metric_name: 'fetch',
        count: 1,
    })
    return result
}
