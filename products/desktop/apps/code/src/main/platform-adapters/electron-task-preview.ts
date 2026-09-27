import {
  app,
  type Cookies,
  type Session,
  session,
  type WebContents,
  type WebPreferences,
  webContents,
} from "electron";
import {
  TASK_PREVIEW_ARG,
  TASK_PREVIEW_PARTITION,
  TASK_PREVIEW_TOKEN_PARAM,
} from "../../shared/constants";

const SANDBOX_PREVIEW_HOST_SUFFIX = ".modal.host";
const LOCAL_PREVIEW_HOSTS = new Set(["localhost", "127.0.0.1"]);

function parseUrl(url: string): URL | null {
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

export function isAllowedTaskPreview(
  src: string,
  partition: string | undefined,
): boolean {
  return partition === TASK_PREVIEW_PARTITION && isAllowedTaskPreviewUrl(src);
}

export function hardenTaskPreviewPreferences(
  preferences: WebPreferences,
  preloadPath: string,
): void {
  preferences.preload = preloadPath;
  preferences.additionalArguments = [TASK_PREVIEW_ARG];
  preferences.nodeIntegration = false;
  preferences.nodeIntegrationInSubFrames = false;
  preferences.contextIsolation = true;
  preferences.sandbox = true;
  preferences.webSecurity = true;
  preferences.allowRunningInsecureContent = false;
  preferences.webviewTag = false;
  preferences.experimentalFeatures = false;
  preferences.enableBlinkFeatures = "";
  preferences.plugins = false;
}

export async function authorizeTaskPreview(
  target: string,
  cookies: Pick<Cookies, "set">,
): Promise<string | null> {
  const url = parseUrl(target);
  if (!url) return null;
  const token = url.searchParams.get(TASK_PREVIEW_TOKEN_PARAM);
  url.searchParams.delete(TASK_PREVIEW_TOKEN_PARAM);
  const bare = url.toString();
  if (!isAllowedTaskPreviewUrl(bare)) return null;
  if (!token) return url.protocol === "http:" ? bare : null;
  if (url.protocol !== "https:") return null;
  await cookies.set({
    url: url.origin,
    name: TASK_PREVIEW_TOKEN_PARAM,
    value: token,
    path: "/",
    secure: true,
    httpOnly: true,
    sameSite: "strict",
  });
  return bare;
}

export function authorizePartitionPreview(
  target: string,
): Promise<string | null> {
  return authorizeTaskPreview(
    target,
    session.fromPartition(TASK_PREVIEW_PARTITION).cookies,
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

const lockedSessions = new WeakSet<Session>();
const NEW_WINDOW_LIMIT = 3;
const NEW_WINDOW_PERIOD_MS = 10_000;

export function createNewWindowLimiter(now: () => number = Date.now) {
  let opened: number[] = [];
  return (): boolean => {
    const time = now();
    opened = opened.filter((at) => time - at < NEW_WINDOW_PERIOD_MS);
    if (opened.length >= NEW_WINDOW_LIMIT) return false;
    opened.push(time);
    return true;
  };
}

export function lockDownTaskPreview(
  guest: WebContents,
  openExternal: (url: string) => void,
): void {
  const mayOpen = createNewWindowLimiter();
  guest.setWindowOpenHandler(({ url }) => {
    if (mayOpen()) openExternal(url);
    return { action: "deny" };
  });
  guest.setWebRTCIPHandlingPolicy("disable_non_proxied_udp");
  let pinnedOrigin: string | null = null;
  const sameOrigin = (url: string) => parseUrl(url)?.origin === pinnedOrigin;
  guest.on("did-start-navigation", (event) => {
    if (pinnedOrigin || !event.isMainFrame) return;
    if (isAllowedTaskPreviewUrl(event.url)) {
      pinnedOrigin = parseUrl(event.url)?.origin ?? null;
    }
  });
  guest.on("will-navigate", (event, url) => {
    if (sameOrigin(url)) return;
    event.preventDefault();
    openExternal(url);
  });
  guest.on("will-redirect", (event, url) => {
    if (event.isMainFrame && pinnedOrigin && !sameOrigin(url)) {
      event.preventDefault();
    }
  });

  lockDownGuestSession(guest.session);
}

export function lockDownGuestSession(guestSession: Session): void {
  if (lockedSessions.has(guestSession)) return;
  lockedSessions.add(guestSession);
  guestSession.setPermissionCheckHandler(() => false);
  guestSession.setPermissionRequestHandler((_contents, _permission, callback) =>
    callback(false),
  );
  guestSession.on("will-download", (event) => event.preventDefault());
  const protectedPorts = protectedLoopbackPorts(
    app.commandLine.getSwitchValue("remote-debugging-port") || undefined,
    process.env.ELECTRON_RENDERER_URL,
  );
  guestSession.webRequest.onBeforeRequest((details, callback) => {
    const pageUrl =
      details.resourceType === "mainFrame"
        ? details.url
        : (details.webContentsId === undefined
            ? undefined
            : webContents.fromId(details.webContentsId)?.getURL()) ||
          "about:blank";
    callback({
      cancel: isBlockedPreviewRequest(pageUrl, details.url, protectedPorts),
    });
  });
}
