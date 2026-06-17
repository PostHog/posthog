/**
 * Tool-name sanitization at the model-provider boundary.
 *
 * Anthropic + OpenAI require tool names to match `^[a-zA-Z0-9_-]{1,128}$`.
 * Our native tools use a `@posthog/<name>` namespace (clean for humans,
 * future-proof for third-party tools) and custom tools can be anything.
 * Both contain characters (`@`, `/`, `.`) that the providers reject.
 *
 * Pattern: build a per-turn map. When emitting tools to pi-ai, rewrite each
 * name to a provider-safe form. When pi-ai returns a tool call, translate
 * the safe name back to the original via the map before dispatch.
 */
const SAFE_RE = /[^a-zA-Z0-9_-]/g
const MAX_LEN = 128

/** Convert a tool id to a provider-safe form. Idempotent on already-safe ids. */
export function providerSafeName(id: string): string {
    let out = id.replace(SAFE_RE, '_')
    if (out.length > MAX_LEN) {
        out = out.slice(0, MAX_LEN)
    }
    return out
}

/**
 * Build a bidirectional name map for one tool list. Returns `safeToOriginal`
 * (used to translate model-emitted tool calls back to dispatch ids).
 *
 * If two distinct originals collapse to the same safe name (e.g. `a.b` and
 * `a_b`), the second wins — callers should treat that as a misconfiguration.
 * In practice native tools use a controlled vocabulary so collisions are not
 * a concern; custom-tool authors can pick non-colliding ids.
 */
export function buildToolNameMap(originalIds: string[]): Map<string, string> {
    const safeToOriginal = new Map<string, string>()
    for (const id of originalIds) {
        safeToOriginal.set(providerSafeName(id), id)
    }
    return safeToOriginal
}
