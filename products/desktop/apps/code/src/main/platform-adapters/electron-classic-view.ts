import type { WebContents, WebPreferences } from "electron";
import { logger } from "../utils/logger";

const ORIGINS = new Set(["https://us.posthog.com", "https://eu.posthog.com"]);
const log = logger.scope("classic-view");

export function isClassicNavigation(
  url: string,
  origin: string,
  projectId?: string,
): boolean {
  try {
    const target = new URL(url);
    return (
      ORIGINS.has(target.origin) &&
      target.origin === origin &&
      !target.username &&
      !target.password &&
      !/^\/(ai|max|chat|code)(\/|$)/.test(target.pathname) &&
      (!projectId ||
        !target.pathname.startsWith("/project/") ||
        target.pathname.match(/^\/project\/(\d+)(?:\/|$)/)?.[1] ===
          projectId) &&
      (!target.pathname.startsWith("/project/") ||
        /^\/project\/\d+(?:\/|$)(?!(?:ai|max|chat|code)(?:\/|$))/.test(
          target.pathname,
        ))
    );
  } catch {
    return false;
  }
}

export function isAllowedClassicView(
  src: string,
  partition: string | undefined,
): boolean {
  try {
    const url = new URL(src);
    return (
      /^posthog-classic-[a-zA-Z0-9-]+$/.test(partition ?? "") &&
      isClassicNavigation(src, url.origin) &&
      /^\/project\/\d+\/dashboards?\/?$/.test(url.pathname)
    );
  } catch {
    return false;
  }
}

export function hardenClassicPreferences(preferences: WebPreferences): void {
  delete preferences.preload;
  preferences.additionalArguments = [];
  preferences.nodeIntegration = false;
  preferences.nodeIntegrationInSubFrames = false;
  preferences.nodeIntegrationInWorker = false;
  preferences.contextIsolation = true;
  preferences.sandbox = true;
  preferences.webSecurity = true;
  preferences.allowRunningInsecureContent = false;
  preferences.webviewTag = false;
  preferences.plugins = false;
  preferences.experimentalFeatures = false;
  preferences.enableBlinkFeatures = "";
}

export function lockDownClassicView(
  guest: WebContents,
  entryUrl: string,
): void {
  const origin = new URL(entryUrl).origin;
  const projectId = new URL(entryUrl).pathname.match(
    /^\/project\/(\d+)\//,
  )?.[1];
  guest.setWindowOpenHandler(() => ({ action: "deny" }));
  guest.session.setPermissionCheckHandler(() => false);
  guest.session.setPermissionRequestHandler(
    (_contents, _permission, callback) => callback(false),
  );
  guest.on("will-navigate", (event, url) => {
    if (!isClassicNavigation(url, origin, projectId)) event.preventDefault();
  });
  guest.on("will-redirect", (event, url) => {
    if (!isClassicNavigation(url, origin, projectId)) event.preventDefault();
  });
  guest.on("will-frame-navigate", (event) => {
    if (event.isMainFrame && !isClassicNavigation(event.url, origin, projectId))
      event.preventDefault();
  });
  guest.on("did-navigate-in-page", (_event, url, isMainFrame) => {
    if (isMainFrame && !isClassicNavigation(url, origin, projectId)) {
      void guest
        .loadURL(entryUrl)
        .catch((error: unknown) =>
          log.warn("Could not return to Classic", { error }),
        );
    }
  });
  guest.on("did-navigate", (_event, url) => {
    const target = new URL(url);
    if (
      target.pathname.match(/^\/project\/(\d+)(?:\/|$)/)?.[1] === projectId &&
      isClassicNavigation(url, origin, projectId) &&
      target.searchParams.get("__desktop_classic") !== "1"
    ) {
      target.searchParams.set("__desktop_classic", "1");
      target.searchParams.set("__desktop_parent_origin", origin);
      void guest
        .loadURL(target.href)
        .catch((error: unknown) =>
          log.warn("Could not load Classic layout", { error }),
        );
    }
  });
}
