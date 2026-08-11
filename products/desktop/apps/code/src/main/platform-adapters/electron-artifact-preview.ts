import path from "node:path";
import type { BrowserWindow, WebContents, WebPreferences } from "electron";
import {
  ARTIFACT_PREVIEW_ARG,
  ARTIFACT_PREVIEW_DATA_URL_PREFIX,
  ARTIFACT_PREVIEW_PARTITION_PREFIX,
} from "../../shared/constants";
import { logger } from "../utils/logger";

const log = logger.scope("artifact-preview-webview");

export function isAllowedArtifactPreview(
  src: string,
  partition: string | undefined,
): boolean {
  return (
    src.startsWith(ARTIFACT_PREVIEW_DATA_URL_PREFIX) &&
    partition?.startsWith(ARTIFACT_PREVIEW_PARTITION_PREFIX) === true
  );
}

export function hardenArtifactPreviewPreferences(
  preferences: WebPreferences,
  preloadPath: string,
): void {
  preferences.preload = preloadPath;
  preferences.additionalArguments = [ARTIFACT_PREVIEW_ARG];
  preferences.nodeIntegration = false;
  preferences.nodeIntegrationInSubFrames = false;
  preferences.contextIsolation = true;
  preferences.sandbox = true;
  preferences.webSecurity = true;
  preferences.allowRunningInsecureContent = false;
  preferences.webviewTag = false;
  preferences.disableDialogs = true;
  preferences.experimentalFeatures = false;
  preferences.enableBlinkFeatures = "";
  preferences.plugins = false;
}

export function lockDownArtifactPreview(guest: WebContents): void {
  guest.setWindowOpenHandler(() => ({ action: "deny" }));
  guest.setWebRTCIPHandlingPolicy("disable_non_proxied_udp");
  guest.on("will-navigate", (event, url) => {
    if (
      url.startsWith(ARTIFACT_PREVIEW_DATA_URL_PREFIX) ||
      url === "about:blank"
    ) {
      return;
    }
    event.preventDefault();
  });
  guest.on("will-frame-navigate", (event) => {
    if (!event.isMainFrame) event.preventDefault();
  });

  const guestSession = guest.session;
  guestSession.enableNetworkEmulation({ offline: true });
  void guestSession
    .setProxy({
      mode: "fixed_servers",
      proxyRules: "http=127.0.0.1:9;https=127.0.0.1:9;socks=127.0.0.1:9",
    })
    .catch((error) =>
      log.warn("Failed to isolate artifact preview proxy", { error }),
    );
  guestSession.setPermissionCheckHandler(() => false);
  guestSession.setPermissionRequestHandler((_contents, _permission, callback) =>
    callback(false),
  );
  guestSession.on("will-download", (event) => event.preventDefault());
  guestSession.webRequest.onBeforeRequest(
    {
      urls: [
        "http://*/*",
        "https://*/*",
        "file://*/*",
        "ws://*/*",
        "wss://*/*",
      ],
    },
    (_details, callback) => callback({ cancel: true }),
  );
}

export function setupArtifactPreviewWebviews(window: BrowserWindow): void {
  const preloadPath = path.join(__dirname, "preload.js");

  window.webContents.on("will-attach-webview", (event, preferences, params) => {
    if (!isAllowedArtifactPreview(params.src, params.partition)) {
      event.preventDefault();
      log.warn("Blocked an unsupported webview attachment");
      return;
    }
    hardenArtifactPreviewPreferences(preferences, preloadPath);
  });

  window.webContents.on("did-attach-webview", (_event, guest) => {
    lockDownArtifactPreview(guest);
  });
}
