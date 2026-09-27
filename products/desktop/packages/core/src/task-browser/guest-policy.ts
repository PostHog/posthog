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

function normalizeHost(hostname: string): string {
  const host = hostname.replace(/^\[|\]$/g, "").toLowerCase();
  const mapped =
    /^::ffff:(?:(\d+\.\d+\.\d+\.\d+)|([0-9a-f]{1,4}):([0-9a-f]{1,4}))$/.exec(
      host,
    );
  if (!mapped) return host;
  if (mapped[1]) return mapped[1];
  const high = Number.parseInt(mapped[2], 16);
  const low = Number.parseInt(mapped[3], 16);
  return [high >> 8, high & 255, low >> 8, low & 255].join(".");
}

function isPrivateNetworkHost(hostname: string): boolean {
  const host = normalizeHost(hostname);
  if (host === "localhost" || host.endsWith(".localhost")) return true;
  if (host === "::1" || host === "::" || host.startsWith("fe80:")) return true;
  if (host.startsWith("fc") || host.startsWith("fd")) return host.includes(":");
  const octets = host.split(".").map(Number);
  if (octets.length !== 4 || octets.some((part) => !Number.isInteger(part))) {
    return false;
  }
  const [a, b] = octets;
  return (
    a === 0 ||
    a === 10 ||
    a === 127 ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    (a === 100 && b >= 64 && b <= 127)
  );
}

function isLoopbackHost(hostname: string): boolean {
  const host = normalizeHost(hostname);
  return (
    host === "localhost" ||
    host.endsWith(".localhost") ||
    host === "::1" ||
    host === "::" ||
    host === "0.0.0.0" ||
    host.startsWith("127.")
  );
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
  if (
    isLoopbackHost(request.hostname) &&
    protectedPorts.has(requestPort(request))
  ) {
    return true;
  }
  const page = parseUrl(pageUrl);
  if (!page) return false;
  return (
    !isPrivateNetworkHost(page.hostname) &&
    isPrivateNetworkHost(request.hostname)
  );
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
