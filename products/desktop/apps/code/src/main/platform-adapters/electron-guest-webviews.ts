import path from "node:path";
import { type BrowserWindow, session } from "electron";
import { TASK_PREVIEW_PARTITION } from "../../shared/constants";
import { openExternalIfSafe } from "../external-links";
import { logger } from "../utils/logger";
import {
  hardenArtifactPreviewPreferences,
  isAllowedArtifactPreview,
  lockDownArtifactPreview,
} from "./electron-artifact-preview";
import {
  hardenTaskPreviewPreferences,
  isAllowedTaskPreview,
  lockDownTaskPreview,
} from "./electron-task-preview";

const log = logger.scope("guest-webviews");

export function setupGuestWebviews(window: BrowserWindow): void {
  const preloadPath = path.join(__dirname, "preload.js");

  window.webContents.on("will-attach-webview", (event, preferences, params) => {
    if (isAllowedTaskPreview(params.src, params.partition)) {
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
    if (guest.session === session.fromPartition(TASK_PREVIEW_PARTITION)) {
      lockDownTaskPreview(guest, openExternalIfSafe);
      return;
    }
    lockDownArtifactPreview(guest);
  });
}
