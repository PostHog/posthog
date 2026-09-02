// Mirrors `@posthog/core/mcp-servers/iconDomain` (mobile doesn't depend on
// @posthog/core, same as the hand-mirrored types in ./types.ts).

// Machine-facing subdomains stripped when deriving a brand domain from a
// server URL, so a custom install at https://mcp.linear.app/mcp still
// resolves the vendor's brand (linear.app).
const STRIPPED_SUBDOMAINS = ["mcp.", "api.", "www."];

/**
 * Best-effort brand domain for an MCP server without a template-provided
 * `icon_domain`: the server URL's hostname with machine-facing subdomains
 * stripped. Null when no plausible brand domain exists (invalid URL, or a
 * dotless host like localhost).
 */
export function iconDomainFromServerUrl(
  serverUrl: string | null | undefined,
): string | null {
  if (!serverUrl) {
    return null;
  }
  let host: string;
  try {
    host = new URL(serverUrl).hostname.toLowerCase();
  } catch {
    return null;
  }
  for (const prefix of STRIPPED_SUBDOMAINS) {
    if (host.startsWith(prefix) && host.split(".").length >= 3) {
      return host.slice(prefix.length);
    }
  }
  return host.includes(".") ? host : null;
}
