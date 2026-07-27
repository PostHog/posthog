/**
 * Shared plumbing for the HTTP-ish native tools (`@posthog/http-request`,
 * `@posthog/github-app-request`). One definition each of the egress budgets,
 * the timeout wrapper, response-body capping, and header selection so the two
 * tools can't drift on policy.
 */

import type { ToolContext } from '@posthog/agent-shared'

/** Platform-wide egress budgets — how much a tool may return to the model and
 *  how long an outbound call may hang. One source so the tools stay in step. */
export const DEFAULT_MAX_RESPONSE_BYTES = 1_000_000
export const ABSOLUTE_MAX_RESPONSE_BYTES = 5_000_000
export const DEFAULT_TIMEOUT_MS = 15_000
export const ABSOLUTE_MAX_TIMEOUT_MS = 60_000

/**
 * Fetch through the tool's proxy-bound client with an abort timeout.
 * `errPrefix` namespaces the thrown error per tool (`http_request`,
 * `github_app_request`) so callers keep their existing error codes.
 */
export async function fetchWithTimeout(
    ctx: ToolContext,
    url: string,
    init: RequestInit,
    timeoutMs: number,
    errPrefix: string
): Promise<Response> {
    const controller = new AbortController()
    const abortTimer = setTimeout(() => controller.abort(), timeoutMs)
    try {
        return await ctx.http.fetch(url, { ...init, signal: controller.signal })
    } catch (err) {
        const e = err as Error & { name?: string }
        if (e.name === 'AbortError') {
            throw new Error(`${errPrefix}_timeout: ${timeoutMs}ms`)
        }
        throw new Error(`${errPrefix}_failed: ${e.message ?? 'unknown'}`)
    } finally {
        clearTimeout(abortTimer)
    }
}

/**
 * Return the allowlisted response headers, keys lower-cased. Sending every
 * header back inflates the model's context for no payoff; lower-casing gives
 * the model one stable spelling to read (`headers['content-type']`).
 */
export function pickHeaders(res: Response, allowlist: ReadonlySet<string>): Record<string, string> {
    const out: Record<string, string> = {}
    for (const [k, v] of res.headers.entries()) {
        const lower = k.toLowerCase()
        if (allowlist.has(lower)) {
            out[lower] = v
        }
    }
    return out
}

/**
 * Read the response body up to `maxBytes`, streaming so an oversized or
 * highly-compressed response is never fully materialized before truncation.
 * Stops at the cap and cancels the stream, which tears down the underlying
 * connection so we don't keep pulling bytes we'll throw away. Falls back to
 * `res.text()` only when the response exposes no readable stream (e.g. an
 * empty body or a non-streaming test mock), still capping the result.
 */
export async function readCappedBody(
    res: Response,
    maxBytes: number
): Promise<{ body: string; bytesRead: number; truncated: boolean }> {
    const stream = res.body
    if (!stream) {
        const text = await res.text()
        const bytes = new TextEncoder().encode(text)
        if (bytes.byteLength <= maxBytes) {
            return { body: text, bytesRead: bytes.byteLength, truncated: false }
        }
        return { body: new TextDecoder().decode(bytes.subarray(0, maxBytes)), bytesRead: maxBytes, truncated: true }
    }

    const reader = stream.getReader()
    const chunks: Uint8Array[] = []
    let total = 0
    let truncated = false
    try {
        while (total < maxBytes) {
            const { done, value } = await reader.read()
            if (done) {
                break
            }
            if (total + value.byteLength > maxBytes) {
                chunks.push(value.subarray(0, maxBytes - total))
                total = maxBytes
                truncated = true
                break
            }
            chunks.push(value)
            total += value.byteLength
        }
    } finally {
        // Cancel rather than drain: releases the socket so we never pull past the cap.
        await reader.cancel().catch(() => {})
    }

    const buf = new Uint8Array(total)
    let offset = 0
    for (const chunk of chunks) {
        buf.set(chunk, offset)
        offset += chunk.byteLength
    }
    return { body: new TextDecoder().decode(buf), bytesRead: total, truncated }
}
