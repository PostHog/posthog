import type { WebContents, WebPreferences } from "electron";
import { logger } from "../utils/logger";

const ORIGINS = new Set(["https://us.posthog.com", "https://eu.posthog.com"]);
const log = logger.scope("classic-view");

export function isClassicNavigation(url: string, origin: string): boolean {
  try {
    const target = new URL(url);
    return (
      ORIGINS.has(target.origin) &&
      target.origin === origin &&
      !target.username &&
      !target.password &&
      (!target.pathname.startsWith("/project/") ||
        /^\/project\/\d+\/(dashboards|insights|saved_insights)(\/|$)/.test(
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
      /^\/project\/\d+\/dashboards\/?$/.test(url.pathname)
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
  guest.setWindowOpenHandler(() => ({ action: "deny" }));
  guest.session.setPermissionCheckHandler(() => false);
  guest.session.setPermissionRequestHandler(
    (_contents, _permission, callback) => callback(false),
  );
  guest.on("will-navigate", (event, url) => {
    if (!isClassicNavigation(url, origin)) event.preventDefault();
  });
  guest.on("will-redirect", (event, url) => {
    if (!isClassicNavigation(url, origin)) event.preventDefault();
  });
  guest.on("will-frame-navigate", (event) => {
    if (event.isMainFrame && !isClassicNavigation(event.url, origin))
      event.preventDefault();
  });
  guest.on("did-navigate-in-page", (_event, url, isMainFrame) => {
    if (isMainFrame && !isClassicNavigation(url, origin)) {
      void guest
        .loadURL(entryUrl)
        .catch((error: unknown) =>
          log.warn("Could not return to dashboards", { error }),
        );
    }
  });
  guest.on("dom-ready", () => {
    void guest
      .insertCSS(`
      .app-layout > .left-nav, #side-panel, [data-attr="ask-ai-button"], [data-attr="open-context-panel-ai-button"] { display: none !important; }
      .app-layout { --left-nav-width: 0px !important; grid-template: 'content' 1fr / minmax(0, 1fr) !important; }
      #main-content { max-width: 100% !important; }
    `)
      .catch((error: unknown) =>
        log.warn("Could not apply Classic layout", { error }),
      );
  });
}
