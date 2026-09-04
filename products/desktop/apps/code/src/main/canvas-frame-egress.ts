import { CANVAS_V2_FRAME_NAME } from "@posthog/shared";

import { logger } from "./utils/logger";

const log = logger.scope("canvas frame egress");

interface RequestFrame {
  name?: string;
}

interface BeforeRequestDetails {
  url: string;
  resourceType: string;
  frame?: RequestFrame | null;
}

export interface RequestBlockingWebRequest {
  onBeforeRequest(
    filter: { urls: string[] },
    listener: (
      details: BeforeRequestDetails,
      callback: (response: { cancel?: boolean }) => void,
    ) => void,
  ): void;
}

interface NavigatingWebContents {
  on(
    event: "will-frame-navigate",
    listener: (details: {
      url: string;
      frame?: RequestFrame | null;
      preventDefault: () => void;
    }) => void,
  ): void;
}

const GUARDED_URL_PATTERNS = [
  "http://*/*",
  "https://*/*",
  "ws://*/*",
  "wss://*/*",
];

export function isAllowedBoardFrameRequest(details: {
  url: string;
  frame?: RequestFrame | null;
}): boolean {
  return details.frame?.name !== CANVAS_V2_FRAME_NAME;
}

export function installCanvasFrameEgressGuard(
  webRequest: RequestBlockingWebRequest,
): void {
  webRequest.onBeforeRequest(
    { urls: GUARDED_URL_PATTERNS },
    (details, callback) => {
      if (isAllowedBoardFrameRequest(details)) {
        callback({});
        return;
      }
      log.warn("Blocked a board fragment request", {
        resourceType: details.resourceType,
        host: hostOf(details.url),
      });
      callback({ cancel: true });
    },
  );
}

export function guardCanvasFrameNavigation(
  webContents: NavigatingWebContents,
): void {
  webContents.on("will-frame-navigate", (details) => {
    if (details.frame?.name !== CANVAS_V2_FRAME_NAME) return;
    if (details.url.startsWith("about:")) return;
    details.preventDefault();
    log.warn("Blocked a board fragment navigation", {
      host: hostOf(details.url),
    });
  });
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return "unknown";
  }
}
