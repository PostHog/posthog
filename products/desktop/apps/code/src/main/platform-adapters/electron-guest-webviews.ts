import path from "node:path";
import { type BrowserWindow, session } from "electron";
import {
  TASK_BROWSER_PARTITION,
  TASK_PREVIEW_PARTITION,
} from "../../shared/constants";
import { openExternalIfSafe } from "../external-links";
import { logger } from "../utils/logger";
import {
  hardenArtifactPreviewPreferences,
  isAllowedArtifactPreview,
  lockDownArtifactPreview,
} from "./electron-artifact-preview";
import {
  isAllowedTaskBrowser,
  lockDownTaskBrowser,
} from "./electron-task-browser";
import {
  hardenTaskPreviewPreferences,
  isAllowedTaskPreview,
  lockDownTaskPreview,
} from "./electron-task-preview";

const log = logger.scope("guest-webviews");

export interface TaskBrowserBridge {
  mayNavigate(webContentsId: number, url: string): boolean;
  openFromPage(
    webContentsId: number,
    url: string,
  ): "opened" | "blocked" | "untracked";
  recordNetwork(webContentsId: number | undefined, text: string): void;
}

function recordFailedRequests(
  partition: string,
  bridge: TaskBrowserBridge,
): void {
  const guestSession = session.fromPartition(partition);
  guestSession.webRequest.onCompleted((details) => {
    if (details.statusCode >= 400) {
      bridge.recordNetwork(
        details.webContentsId,
        `${details.statusCode} ${details.method} ${details.url}`,
      );
    }
  });
  guestSession.webRequest.onErrorOccurred((details) => {
    bridge.recordNetwork(
      details.webContentsId,
      `${details.error} ${details.method} ${details.url}`,
    );
  });
}

export function setupGuestWebviews(
  window: BrowserWindow,
  bridge?: TaskBrowserBridge,
): void {
  const preloadPath = path.join(__dirname, "preload.js");
  if (bridge) {
    recordFailedRequests(TASK_PREVIEW_PARTITION, bridge);
    recordFailedRequests(TASK_BROWSER_PARTITION, bridge);
  }

  window.webContents.on("will-attach-webview", (event, preferences, params) => {
    if (
      isAllowedTaskPreview(params.src, params.partition) ||
      isAllowedTaskBrowser(params.src, params.partition)
    ) {
      hardenTaskPreviewPreferences(preferences, preloadPath);
      return;
    }
    if (isAllowedArtifactPreview(params.src, params.partition)) {
      hardenArtifactPreviewPreferences(preferences, preloadPath);
      return;
    }
    event.preventDefault();
    log.warn("Blocked an unsupported webview attachment");
  });

  window.webContents.on("did-attach-webview", (_event, guest) => {
    if (guest.session === session.fromPartition(TASK_BROWSER_PARTITION)) {
      lockDownTaskBrowser(guest, {
        openInApp: (url, source) => {
          const outcome = bridge?.openFromPage(source.id, url) ?? "untracked";
          if (outcome === "untracked") openExternalIfSafe(url);
        },
        mayNavigate: (url, source) =>
          bridge?.mayNavigate(source.id, url) ?? true,
        openExternal: openExternalIfSafe,
      });
      return;
    }
    if (guest.session === session.fromPartition(TASK_PREVIEW_PARTITION)) {
      lockDownTaskPreview(guest, openExternalIfSafe);
      return;
    }
    lockDownArtifactPreview(guest);
  });
}
