/** Hosts whose dev servers almost never terminate TLS — default them to http. */
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "0.0.0.0", "[::1]"]);

function parseWebUrl(raw: string): string | null {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return null;
  if (!url.hostname) return null;
  return url.href;
}

/**
 * "localhost:8000" parses as a URL with the scheme "localhost", so a plain
 * scheme check would misread host:port shorthand as a custom scheme. A real
 * non-web scheme (javascript:, file:, mailto:) never continues with a bare
 * port number.
 */
function hasNonWebScheme(input: string): boolean {
  const match = input.match(/^([a-zA-Z][a-zA-Z0-9+.-]*):(.*)$/);
  if (!match) return false;
  const scheme = match[1].toLowerCase();
  if (scheme === "http" || scheme === "https") return false;
  return !/^\d+([/?#].*)?$/.test(match[2]);
}

/**
 * Normalize user-typed input into a loadable http(s) URL, or null when it
 * cannot be one. This is the single URL policy for the embedded browser:
 * anything the native view loads must pass through here first.
 */
export function normalizeBrowserUrl(input: string): string | null {
  const trimmed = input.trim();
  if (!trimmed || /\s/.test(trimmed)) return null;
  if (hasNonWebScheme(trimmed)) return null;

  const direct = parseWebUrl(trimmed);
  if (direct) return direct;
  // Claimed a scheme but didn't parse to a valid web URL ("https://") —
  // prefixing another scheme onto it would fabricate a bogus host.
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(trimmed)) return null;

  const host = trimmed.split(/[/:?#]/, 1)[0]?.toLowerCase() ?? "";
  const scheme = LOCAL_HOSTS.has(host) ? "http" : "https";
  return parseWebUrl(`${scheme}://${trimmed}`);
}
