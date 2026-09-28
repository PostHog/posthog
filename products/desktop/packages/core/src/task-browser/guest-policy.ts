import { isPrivateIpv4Octets, isPrivateIpv6Literal } from "@posthog/shared";
import { TASK_PREVIEW_TOKEN_PARAM } from "@posthog/shared/constants";

const SANDBOX_PREVIEW_HOST_SUFFIX = ".modal.host";
const LOCAL_PREVIEW_HOSTS = new Set(["localhost", "127.0.0.1"]);
const NEW_WINDOW_LIMIT = 3;
const NEW_WINDOW_PERIOD_MS = 10_000;
const WEB_PROTOCOLS = new Set(["http:", "https:"]);

export function parseUrl(url: string): URL | null {
  try {
    return new URL(url);
  } catch {
    return null;
  }
}

export function isAllowedTaskPreviewUrl(url: string): boolean {
  const parsed = parseUrl(url);
  if (!parsed || parsed.username || parsed.password) return false;
  if (parsed.searchParams.has(TASK_PREVIEW_TOKEN_PARAM)) return false;
  if (
    parsed.protocol === "https:" &&
    parsed.hostname.endsWith(SANDBOX_PREVIEW_HOST_SUFFIX)
  ) {
    return true;
  }
  return (
    parsed.protocol === "http:" && LOCAL_PREVIEW_HOSTS.has(parsed.hostname)
  );
}

const PRIVATE_HOST_SUFFIXES = [
  ".local",
  ".localhost",
  ".internal",
  ".lan",
  ".home",
  ".home.arpa",
  ".ts.net",
];
const NETWORK_PROTOCOLS = new Set(["http:", "https:", "ws:", "wss:"]);

function normalizeHost(hostname: string): string {
  return hostname
    .replace(/^\[|\]$/g, "")
    .toLowerCase()
    .replace(/\.$/, "");
}

function parseIpv4(host: string): [number, number, number, number] | null {
  const match = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (!match) return null;
  const octets = match.slice(1).map(Number);
  if (octets.some((octet) => octet > 255)) return null;
  return octets as [number, number, number, number];
}

function mappedIpv4(host: string): [number, number, number, number] | null {
  const hex = host.match(/^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/);
  if (hex) {
    const high = Number.parseInt(hex[1], 16);
    const low = Number.parseInt(hex[2], 16);
    return [high >> 8, high & 255, low >> 8, low & 255];
  }
  const dotted = host.match(/^::ffff:(\d{1,3}(?:\.\d{1,3}){3})$/);
  return dotted ? parseIpv4(dotted[1]) : null;
}

function isPrivateNetworkHost(hostname: string): boolean {
  const host = normalizeHost(hostname);
  if (!host) return false;
  if (host === "localhost") return true;
  if (host.includes(":")) return isPrivateIpv6Literal(host);
  const octets = parseIpv4(host);
  if (octets) return isPrivateIpv4Octets(octets[0], octets[1]);
  if (!host.includes(".")) return true;
  return PRIVATE_HOST_SUFFIXES.some((suffix) => host.endsWith(suffix));
}

function isLoopbackHost(hostname: string): boolean {
  const host = normalizeHost(hostname);
  if (host === "localhost" || host.endsWith(".localhost")) return true;
  if (host === "::1" || host === "::" || host === "::0") return true;
  const octets = host.includes(":") ? mappedIpv4(host) : parseIpv4(host);
  if (!octets) return false;
  return octets[0] === 127 || octets.every((octet) => octet === 0);
}

function requestPort(url: URL): number {
  if (url.port) return Number(url.port);
  return url.protocol === "https:" || url.protocol === "wss:" ? 443 : 80;
}

export function protectedLoopbackPorts(
  cdpPort: string | undefined,
  rendererUrl: string | undefined,
): ReadonlySet<number> {
  const ports = new Set<number>();
  const cdp = Number(cdpPort);
  if (Number.isInteger(cdp) && cdp > 0) ports.add(cdp);
  const renderer = rendererUrl ? parseUrl(rendererUrl) : null;
  if (renderer) ports.add(requestPort(renderer));
  return ports;
}

export function isBlockedPreviewRequest(
  pageUrl: string,
  requestUrl: string,
  protectedPorts: ReadonlySet<number> = new Set(),
): boolean {
  const request = parseUrl(requestUrl);
  if (!request) return true;
  if (
    !["http:", "https:", "ws:", "wss:", "data:", "blob:"].includes(
      request.protocol,
    )
  ) {
    return true;
  }
  if (!NETWORK_PROTOCOLS.has(request.protocol)) return false;
  if (
    isLoopbackHost(request.hostname) &&
    protectedPorts.has(requestPort(request))
  ) {
    return true;
  }
  const page = parseUrl(pageUrl);
  const pageIsPrivate =
    !!page &&
    WEB_PROTOCOLS.has(page.protocol) &&
    isPrivateNetworkHost(page.hostname);
  return !pageIsPrivate && isPrivateNetworkHost(request.hostname);
}

export function createNewWindowLimiter(
  now: () => number = Date.now,
): () => boolean {
  let opened: number[] = [];
  return (): boolean => {
    const time = now();
    opened = opened.filter((at) => time - at < NEW_WINDOW_PERIOD_MS);
    if (opened.length >= NEW_WINDOW_LIMIT) return false;
    opened.push(time);
    return true;
  };
}

export function isAllowedTaskBrowserUrl(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  return (
    WEB_PROTOCOLS.has(parsed.protocol) &&
    !parsed.username &&
    !parsed.password &&
    !parsed.searchParams.has(TASK_PREVIEW_TOKEN_PARAM)
  );
}
