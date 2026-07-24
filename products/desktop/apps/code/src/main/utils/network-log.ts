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

const SENSITIVE_QUERY_PARAMS = new Set([
  "secret",
  "token",
  "access_token",
  "refresh_token",
  "id_token",
  "code",
  "signature",
  "api_key",
  "apikey",
  "client_secret",
  "password",
  "session",
  "x-amz-signature",
  "x-amz-credential",
  "x-amz-security-token",
]);

export function redactUrl(rawUrl: string): string {
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    const [base] = rawUrl.split("?");
    return rawUrl.includes("?") ? `${base}?<redacted>` : rawUrl;
  }

  for (const key of new Set(parsed.searchParams.keys())) {
    if (SENSITIVE_QUERY_PARAMS.has(key.toLowerCase())) {
      parsed.searchParams.set(key, "***");
    }
  }
  return parsed.toString();
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
