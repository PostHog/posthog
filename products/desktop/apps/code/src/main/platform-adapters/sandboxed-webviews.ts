import { SKETCHPAD_PARTITION, SKETCHPAD_URL } from "@posthog/shared";
import type { Session, WebContents, WebPreferences } from "electron";
import {
  ARTIFACT_PREVIEW_ARG,
  ARTIFACT_PREVIEW_DATA_URL_PREFIX,
  ARTIFACT_PREVIEW_PARTITION_PREFIX,
  SKETCHPAD_ARG,
} from "../../shared/constants";
import { logger } from "../utils/logger";

const log = logger.scope("sandboxed webviews");

export interface SandboxedWebviewKind {
  matches(src: string, partition: string | undefined): boolean;
  additionalArgument: string;
  allowsNavigationTo(url: string): boolean;
}

export const ARTIFACT_PREVIEW_KIND: SandboxedWebviewKind = {
  matches: (src, partition) =>
    src.startsWith(ARTIFACT_PREVIEW_DATA_URL_PREFIX) &&
    partition?.startsWith(ARTIFACT_PREVIEW_PARTITION_PREFIX) === true,
  additionalArgument: ARTIFACT_PREVIEW_ARG,
  allowsNavigationTo: (url) =>
    url.startsWith(ARTIFACT_PREVIEW_DATA_URL_PREFIX) || url === "about:blank",
};

export const SKETCHPAD_KIND: SandboxedWebviewKind = {
  matches: (src, partition) =>
    src === SKETCHPAD_URL && partition === SKETCHPAD_PARTITION,
  additionalArgument: SKETCHPAD_ARG,
  allowsNavigationTo: (url) => url === SKETCHPAD_URL,
};

export function lockDownGuest(
  guest: WebContents,
  kind: SandboxedWebviewKind,
): void {
  guest.setWindowOpenHandler(() => ({ action: "deny" }));
  guest.setWebRTCIPHandlingPolicy("disable_non_proxied_udp");
  guest.on("will-navigate", (event, url) => {
    if (!kind.allowsNavigationTo(url)) event.preventDefault();
  });
  guest.on("will-frame-navigate", (event) => {
    if (!event.isMainFrame) event.preventDefault();
  });
}

export function isolateGuestSession(guestSession: Session): void {
  guestSession.enableNetworkEmulation({ offline: true });
  void guestSession
    .setProxy({
      mode: "fixed_servers",
      proxyRules: "http=127.0.0.1:9;https=127.0.0.1:9;socks=127.0.0.1:9",
    })
    .catch((error) => log.warn("Failed to isolate guest proxy", { error }));
  guestSession.setPermissionCheckHandler(() => false);
  guestSession.setPermissionRequestHandler((_contents, _permission, done) =>
    done(false),
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

export function hardenGuestPreferences(
  preferences: WebPreferences,
  preloadPath: string,
  kind: SandboxedWebviewKind,
): void {
  preferences.preload = preloadPath;
  preferences.additionalArguments = [kind.additionalArgument];
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
