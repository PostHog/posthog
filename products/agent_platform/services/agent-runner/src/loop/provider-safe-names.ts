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
    // A leading *unsafe* char (the `@` in `@posthog/meta-end-turn`) would become
    // a leading underscore — but models routinely drop it when they echo the
    // name back, calling `posthog_meta-end-turn` for a tool we'd otherwise
    // register as `_posthog_meta-end-turn`. The reverse map then misses and the
    // call dispatches as "not found" (it self-corrects next turn, but burns a
    // turn + emits a spurious tool error every session). Strip the leading
    // underscores that sanitization introduced so the safe name matches the
    // model's natural form. A name that was already a legal `_foo` keeps it.
    if (/^[^a-zA-Z0-9_-]/.test(id)) {
        const stripped = out.replace(/^_+/, '')
        if (stripped.length > 0) {
            out = stripped
        }
    }
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
        const safe = providerSafeName(id)
        const existing = safeToOriginal.get(safe)
        if (existing !== undefined && existing !== id) {
            // Two distinct ids collapsed to the same provider-safe name (e.g. a
            // `.`-vs-`_` clash, or two long ids sharing a 128-char prefix after
            // truncation). The second wins and the first becomes undispatchable.
            // Native ids use a controlled vocab, so this is a custom-tool
            // misconfiguration — warn loudly rather than silently strand a tool.
            // eslint-disable-next-line no-console -- build-time misconfig signal, not a hot path
            console.warn(
                `[provider-safe-names] tool-name collision: "${existing}" and "${id}" both map to "${safe}"; "${id}" wins and the other is undispatchable`
            )
        }
        safeToOriginal.set(safe, id)
    }
    return safeToOriginal
}
