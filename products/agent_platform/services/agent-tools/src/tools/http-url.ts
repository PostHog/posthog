/**
 * Shared URL validation for the agent-facing HTTP tools (`@posthog/http-request`,
 * `@posthog/web-fetch`).
 *
 * SSRF (host/IP filtering) is enforced at the egress hop by smokescreen, but
 * that only governs WHERE a request can go — not the scheme. `new URL()` alone
 * happily parses `file://`, `gopher://`, `data:`, etc., and whether those are
 * refused depends on undici's incidental behaviour rather than an explicit
 * app guard. Pin the scheme to http/https here so a model-supplied URL can't
 * reach a non-HTTP fetch surface. Mirrors the explicit `https:` check the MCP
 * transport already enforces in `mcp-clients.ts`.
 */
const ALLOWED_SCHEMES = new Set(['http:', 'https:'])

/**
 * Parse `url` and require an http/https scheme. Throws a model-readable error
 * (`invalid_url` / `unsupported_url_scheme`) the agent can retry against.
 */
export function parseFetchableUrl(url: string): URL {
    let parsed: URL
    try {
        parsed = new URL(url)
    } catch {
        throw new Error(`invalid_url: ${url}`)
    }
    if (!ALLOWED_SCHEMES.has(parsed.protocol)) {
        throw new Error(`unsupported_url_scheme: ${parsed.protocol} (only http/https are allowed)`)
    }
    return parsed
}
