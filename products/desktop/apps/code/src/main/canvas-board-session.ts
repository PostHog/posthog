import {
  CANVAS_V2_BOARD_PARTITION,
  CANVAS_V2_BOARD_URL,
} from "@posthog/shared";
import type { WebContents, WebPreferences } from "electron";
import { session } from "electron";
import { CANVAS_BOARD_ARG } from "../shared/constants";

import { registerCanvasModulesProtocol } from "./protocols/canvas-modules";
import { canvasModulesResourcesDir } from "./protocols/canvas-modules-dir";
import { logger } from "./utils/logger";

const log = logger.scope("canvas board session");

const DEAD_PROXY = "http=127.0.0.1:9;https=127.0.0.1:9;socks=127.0.0.1:9";

export function prepareCanvasBoardSession(): void {
  const boardSession = session.fromPartition(CANVAS_V2_BOARD_PARTITION);

  registerCanvasModulesProtocol(
    boardSession.protocol,
    canvasModulesResourcesDir(),
  );

  void boardSession
    .setProxy({ mode: "fixed_servers", proxyRules: DEAD_PROXY })
    .catch((error) => log.warn("Board proxy not set", { error }));

  boardSession.setPermissionRequestHandler((_contents, _permission, done) =>
    done(false),
  );
  boardSession.setPermissionCheckHandler(() => false);
  boardSession.on("will-download", (event) => event.preventDefault());
  boardSession.webRequest.onBeforeRequest(
    { urls: ["http://*/*", "https://*/*", "ws://*/*", "wss://*/*"] },
    (details, callback) => {
      log.warn("Blocked a board request", {
        resourceType: details.resourceType,
      });
      callback({ cancel: true });
    },
  );
}

export function hardenCanvasBoardPreferences(
  preferences: WebPreferences,
  preloadPath: string,
): void {
  preferences.preload = preloadPath;
  preferences.additionalArguments = [CANVAS_BOARD_ARG];
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

export function lockDownCanvasBoard(guest: WebContents): void {
  guest.setWindowOpenHandler(() => ({ action: "deny" }));
  guest.setWebRTCIPHandlingPolicy("disable_non_proxied_udp");
  guest.on("will-navigate", (event, url) => {
    if (url.startsWith(CANVAS_V2_BOARD_URL)) return;
    event.preventDefault();
    log.warn("Blocked a board navigation");
  });
  guest.on("will-frame-navigate", (event) => {
    if (!event.isMainFrame) event.preventDefault();
  });
}

export function isCanvasBoardGuest(guest: WebContents): boolean {
  const url = typeof guest.getURL === "function" ? guest.getURL() : "";
  return url.startsWith(CANVAS_V2_BOARD_URL);
}

export function isCanvasBoardWebview(
  src: string,
  partition: string | undefined,
): boolean {
  return src === CANVAS_V2_BOARD_URL && partition === CANVAS_V2_BOARD_PARTITION;
}
