import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import { AsyncFunctionContext } from '../async-function-registry'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { fetchErrorDetail } from '../utils/cdp-fetch'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

// Rolling deploys drop in-flight connections, so one quick retry round matters; anything
// longer would block the consumer loop, which is why the queued-fetch path exists for
// third-party calls.
const MAX_ATTEMPTS = 3
const BACKOFF_MS = 250
const RETRIABLE_STATUSES = [502, 503, 504]

/**
 * Calls an internal-only Django route (/api/projects/<team_id>/internal/...) on behalf of a
 * first-party async function, and pushes the `{status, body}` response onto the resumed VM
 * stack (see the RETURN-VALUE CONTRACT in example.ts).
 *
 * Runs inline instead of through queueParameters on purpose:
 * - the queued-fetch executor's SSRF guard refuses in-cluster hosts, and exempting them
 *   would hand that bypass to user-settable queue data;
 * - nothing is persisted, so no credential ever lands in a job row — a fresh short-lived
 *   token is minted per attempt (same reasoning as the SigV4 signing in executeFetch).
 *
 * The team claim always comes from the invocation, never from Hog-provided arguments.
 */
export async function callInternalApi(
    context: AsyncFunctionContext,
    result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
    options: {
        jwt: ScopedServiceJwt
        path: `/${string}`
        method: 'GET' | 'PATCH' | 'POST'
        entityClaims: Record<string, string>
        body?: string
        extraHeaders?: Record<string, string>
    }
): Promise<void> {
    const { jwt, path, method, entityClaims, body, extraHeaders } = options
    const startedAt = performance.now()

    let response: { status: number; body: unknown } | null = null

    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
        // Fresh token per attempt: nothing stored, nothing reusable after the short TTL.
        // team_id spreads last so no entityClaims value can ever override the trusted team.
        const token = jwt.mint({ ...entityClaims, team_id: context.invocation.teamId })

        let fetchError: Error | null = null
        let status: number | null = null
        let text: string | null = null
        try {
            const fetchResponse = await internalFetch(`${context.internalApiBaseUrl}${path}`, {
                method,
                headers: {
                    'Content-Type': 'application/json',
                    ...extraHeaders,
                    Authorization: `Bearer ${token}`,
                },
                ...(body !== undefined ? { body } : {}),
            })
            status = fetchResponse.status
            text = await fetchResponse.text()
        } catch (err) {
            fetchError = err as Error
        }

        if (status !== null && !RETRIABLE_STATUSES.includes(status)) {
            let parsedBody: unknown = text
            try {
                parsedBody = text ? parseJSON(text) : undefined
            } catch {
                // Non-JSON body passes through as text
            }
            if (status >= 400) {
                result.logs.push({
                    level: 'error',
                    timestamp: DateTime.now(),
                    message: `Internal API call failed with status code ${status}.`,
                })
            }
            response = { status, body: parsedBody }
            break
        }

        const willRetry = attempt < MAX_ATTEMPTS
        result.logs.push({
            level: willRetry ? 'info' : 'error',
            timestamp: DateTime.now(),
            message:
                `Internal API call failed on attempt ${attempt} with status code ${status ?? '(none)'}.` +
                (fetchError ? ` Error: ${fetchErrorDetail(fetchError)}.` : '') +
                (willRetry ? ' Retrying.' : ''),
        })

        if (!willRetry) {
            // Same shape executeFetch pushes on a client-side failure, so template guards
            // like `if (response.status != 200) throw` keep firing.
            response = {
                status: status ?? 500,
                body: fetchError ? `${fetchError.name}: ${fetchErrorDetail(fetchError)}` : undefined,
            }
            break
        }
        await new Promise((resolve) => setTimeout(resolve, BACKOFF_MS * attempt))
    }

    result.invocation.state.timings.push({
        kind: 'async_function',
        duration_ms: Math.round(performance.now() - startedAt),
    })
    result.metrics.push({
        team_id: context.invocation.teamId,
        app_source_id: context.invocation.parentRunId ?? context.invocation.functionId,
        metric_kind: 'other',
        metric_name: 'fetch',
        count: 1,
    })

    result.invocation.state.vmState?.stack.push(response)
}
