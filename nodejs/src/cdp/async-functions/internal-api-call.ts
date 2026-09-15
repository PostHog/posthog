import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import { AsyncFunctionContext } from '../async-function-registry'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { RETRIABLE_STATUS_CODES, fetchErrorDetail } from '../utils/cdp-fetch'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

// Rolling deploys drop in-flight connections, so one quick retry round matters; anything
// longer would block the consumer loop, which is why the queued-fetch path exists for
// third-party calls.
const MAX_ATTEMPTS = 3
const BACKOFF_MS = 250
// Same statuses the queued-fetch path retries (cdp-fetch.ts), so a transient Django 500
// gets the same resilience here that it would have gotten through executeFetch.
const RETRIABLE_STATUSES = RETRIABLE_STATUS_CODES

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

    // Counts once per handler call, not per retry attempt below: the retries are all one
    // logical step from the VM's point of view, and the counted queued-fetch path only
    // counts once per queued fetch too.
    context.consumeInlineAsyncBudget()

    const parseBody = (text: string | null): unknown => {
        try {
            return text ? parseJSON(text) : undefined
        } catch {
            // Non-JSON body passes through as text
            return text
        }
    }

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
            // Covers both a failed fetch (status stays null) and a body-read failure after a
            // successful status line (status is set but the response can't be trusted) — either
            // way this attempt did not complete, so it must not be treated as a success below.
            fetchError = err as Error
        }

        const succeeded = fetchError === null && status !== null && !RETRIABLE_STATUSES.includes(status)
        if (succeeded) {
            const parsedBody = parseBody(text)
            if (status! >= 400) {
                result.logs.push({
                    level: 'error',
                    timestamp: DateTime.now(),
                    message: `Internal API call failed with status code ${status}.`,
                })
            }
            response = { status: status!, body: parsedBody }
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
            if (status !== null && fetchError === null) {
                // A real HTTP response came back (a retriable status like 503) and its body was
                // read cleanly — keep it so templates and logs still see what upstream said,
                // matching what executeFetch preserves on its own final failing attempt.
                response = { status, body: parseBody(text) }
            } else {
                // Same shape executeFetch pushes on a client-side failure, so template guards
                // like `if (response.status != 200) throw` keep firing. Also covers a body-read
                // failure after a 200 header: without fetchError === null above, that never
                // reaches the success branch and lands here as a proper failure instead of a
                // silently empty 200.
                response = {
                    status: 500,
                    body: fetchError ? `${fetchError.name}: ${fetchErrorDetail(fetchError)}` : undefined,
                }
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
