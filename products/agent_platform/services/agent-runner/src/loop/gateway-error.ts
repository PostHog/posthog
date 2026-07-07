/**
 * Classifies a pi-ai error message into a gateway-specific failure mode when
 * the session ran through PostHog's ai-gateway. Used at the two pi-ai error
 * paths in `run-turn.ts`:
 *   - the catch around `pi.stream()` (synchronous throws / abort).
 *   - the post-stream `result.stopReason === 'error'` branch (provider
 *     returned an error event).
 *
 * Why string-matching: pi-ai's openai-completions provider sets
 * `output.errorMessage = error.message` on its outer catch (see
 * `pi-ai/src/providers/openai-completions.ts`). For HTTP errors that message
 * is produced by the OpenAI SDK's `APIError.makeMessage(status, error, message)`,
 * which prefixes `${status} ` — see `openai/core/error.js:21-38`. So a regex
 * over the prefix is the cheapest reliable signal we have without patching
 * pi-ai to surface the underlying `error.status`.
 */

export interface GatewayErrorClassification {
    /** HTTP status pulled off the error message prefix. */
    status: number
    /** What the runner should do with this session. */
    kind: 'insufficient_credits' | 'throttled' | 'auth_failed' | 'bad_request' | 'upstream' | 'other'
}

const STATUS_PREFIX_RE = /^(\d{3})\b/

export function classifyGatewayError(errorMessage: string | undefined): GatewayErrorClassification | null {
    if (!errorMessage) {
        return null
    }
    const m = errorMessage.match(STATUS_PREFIX_RE)
    if (!m) {
        return null
    }
    const status = Number(m[1])
    switch (status) {
        case 402:
            // Wallet empty or kill switch tripped — both surface as 402 in the
            // gateway's envelope. The runner can't tell them apart without
            // /v1/wallet/balance, so today both fail the session terminally.
            return { status, kind: 'insufficient_credits' }
        case 429:
            // Front-line throttle. Runner suspends — the queue re-claims the
            // row once the rate-limit window clears.
            return { status, kind: 'throttled' }
        case 401:
            // Bearer revoked or stale phc_ cache. Retrying won't help the
            // same session; the team must rotate or reset its api_token.
            return { status, kind: 'auth_failed' }
        case 400:
            // Disallowed model / shape mismatch / bad body. Spec-level bug,
            // not a transient. Terminal.
            return { status, kind: 'bad_request' }
        case 502:
        case 503:
        case 504:
            // Fallback chain exhausted or upstream provider issue. Treat as
            // transient — the queue retries.
            return { status, kind: 'upstream' }
        default:
            return { status, kind: 'other' }
    }
}
