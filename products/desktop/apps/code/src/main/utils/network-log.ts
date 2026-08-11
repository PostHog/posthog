import { networkLog } from "./logger";

export interface NetworkLogEntry {
  origin: "main" | "renderer";
  method: string;
  url: string;
  status: number | null;
  durationMs: number;
  bytes: number | null;
  error?: string;
}

const LOOPBACK_HOSTNAMES = new Set(["localhost", "::1", "[::1]", "0.0.0.0"]);

export function isLoopbackHost(hostname: string): boolean {
  const host = hostname.toLowerCase();
  return LOOPBACK_HOSTNAMES.has(host) || host.startsWith("127.");
}

export function shouldLogUrl(url: string): boolean {
  try {
    return !isLoopbackHost(new URL(url).hostname);
  } catch {
    return true;
  }
}

// Query strings and URL fragments are treated as entirely sensitive: they
// routinely carry tokens under arbitrary, caller-chosen keys, so no allowlist
// can be trusted. We replace the whole component with a marker instead.
const REDACTED = "<redacted>";

// Credential-shaped path segments to strip even without a query string, e.g. a
// remote MCP endpoint that embeds its API key in the path.
const KEY_SHAPED_SEGMENT =
  /^(?:sk|pk|rk|ghp|gho|ghs|ghr|ghu|xox[baprs]|glpat|shpat|shpss)[_-][A-Za-z0-9]/i;
const AWS_KEY_SEGMENT = /^(?:AKIA|ASIA)[0-9A-Z]{16}$/;
const UUID_SEGMENT =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TOKEN_CHARSET = /^[A-Za-z0-9._~+/=-]+$/;

function safeDecodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

function looksLikeSecretSegment(segment: string): boolean {
  const value = safeDecodeSegment(segment);
  if (KEY_SHAPED_SEGMENT.test(value) || AWS_KEY_SEGMENT.test(value))
    return true;
  // Resource identifiers (UUIDs) are not secrets; keep them for debugging.
  if (UUID_SEGMENT.test(value)) return false;
  // Long, high-entropy tokens: base64url/hex mixing letters and digits.
  if (
    value.length >= 24 &&
    TOKEN_CHARSET.test(value) &&
    /[A-Za-z]/.test(value) &&
    /[0-9]/.test(value)
  ) {
    return true;
  }
  // Long pure-hex digests (session ids, signatures, etc.).
  return value.length >= 32 && /^[0-9a-f]+$/i.test(value);
}

function redactPath(pathname: string): string {
  return pathname
    .split("/")
    .map((segment) => (looksLikeSecretSegment(segment) ? REDACTED : segment))
    .join("/");
}

// Logs only scheme + host + coarse path. Userinfo, the entire query string, and
// any URL fragment are dropped, and credential-shaped path segments are masked,
// so secrets never reach the world-readable network log.
export function redactUrl(rawUrl: string): string {
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    const [base] = rawUrl.split("?");
    const path = redactPath(base);
    return rawUrl.includes("?") ? `${path}?${REDACTED}` : path;
  }

  // Strip embedded credentials (user:pass@host).
  parsed.username = "";
  parsed.password = "";
  const path = redactPath(parsed.pathname);
  const query = parsed.search ? `?${REDACTED}` : "";
  const fragment = parsed.hash ? `#${REDACTED}` : "";
  return `${parsed.protocol}//${parsed.host}${path}${query}${fragment}`;
}

export function parseContentLength(
  value: string | null | undefined,
): number | null {
  if (!value) return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

export function formatBytes(bytes: number | null): string {
  return bytes === null ? "-" : `${bytes}B`;
}

export function levelForEntry(
  entry: NetworkLogEntry,
): "info" | "warn" | "error" {
  if (entry.status === null || entry.status >= 500) return "error";
  if (entry.status >= 400) return "warn";
  return "info";
}

export function formatNetworkLine(entry: NetworkLogEntry): string {
  const outcome =
    entry.status !== null
      ? String(entry.status)
      : `ERR "${entry.error ?? "unknown error"}"`;
  return `[${entry.origin}] ${entry.method.toUpperCase()} ${redactUrl(entry.url)} -> ${outcome} ${Math.round(entry.durationMs)}ms ${formatBytes(entry.bytes)}`;
}

export function recordNetworkRequest(entry: NetworkLogEntry): void {
  try {
    if (!shouldLogUrl(entry.url)) return;
    networkLog[levelForEntry(entry)](formatNetworkLine(entry));
  } catch {
    // Logging must never break the request it observed
  }
}
