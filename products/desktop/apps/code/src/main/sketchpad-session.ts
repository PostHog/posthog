import { SKETCHPAD_PARTITION, SKETCHPAD_URL } from "@posthog/shared";
import type { WebContents, WebPreferences } from "electron";
import { session } from "electron";
import { SKETCHPAD_ARG } from "../shared/constants";

import { registerSketchpadModulesProtocol } from "./protocols/sketchpad-modules";
import { sketchpadModulesResourcesDir } from "./protocols/sketchpad-modules-dir";
import { logger } from "./utils/logger";

const log = logger.scope("sketchpad session");

const DEAD_PROXY = "http=127.0.0.1:9;https=127.0.0.1:9;socks=127.0.0.1:9";

export function prepareSketchpadSession(): void {
  const sketchpadSession = session.fromPartition(SKETCHPAD_PARTITION);

  registerSketchpadModulesProtocol(
    sketchpadSession.protocol,
    sketchpadModulesResourcesDir(),
  );

  void sketchpadSession
    .setProxy({ mode: "fixed_servers", proxyRules: DEAD_PROXY })
    .catch((error) => log.warn("Sketchpad proxy not set", { error }));

  sketchpadSession.setPermissionRequestHandler((_contents, _permission, done) =>
    done(false),
  );
  sketchpadSession.setPermissionCheckHandler(() => false);
  sketchpadSession.on("will-download", (event) => event.preventDefault());
  sketchpadSession.webRequest.onBeforeRequest(
    { urls: ["http://*/*", "https://*/*", "ws://*/*", "wss://*/*"] },
    (details, callback) => {
      log.warn("Blocked a board request", {
        resourceType: details.resourceType,
      });
      callback({ cancel: true });
    },
  );
}

export function hardenSketchpadPreferences(
  preferences: WebPreferences,
  preloadPath: string,
): void {
  preferences.preload = preloadPath;
  preferences.additionalArguments = [SKETCHPAD_ARG];
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

export function lockDownSketchpad(guest: WebContents): void {
  guest.setWindowOpenHandler(() => ({ action: "deny" }));
  guest.setWebRTCIPHandlingPolicy("disable_non_proxied_udp");
  guest.on("will-navigate", (event, url) => {
    if (url.startsWith(SKETCHPAD_URL)) return;
    event.preventDefault();
    log.warn("Blocked a board navigation");
  });
  guest.on("will-frame-navigate", (event) => {
    if (!event.isMainFrame) event.preventDefault();
  });
}

export function isSketchpadGuest(guest: WebContents): boolean {
  const url = typeof guest.getURL === "function" ? guest.getURL() : "";
  return url.startsWith(SKETCHPAD_URL);
}

export function isSketchpadWebview(
  src: string,
  partition: string | undefined,
): boolean {
  return src === SKETCHPAD_URL && partition === SKETCHPAD_PARTITION;
}
