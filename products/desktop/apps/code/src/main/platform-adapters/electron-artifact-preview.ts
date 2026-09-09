import path from "node:path";
import { SKETCHPAD_PARTITION } from "@posthog/shared";
import { type BrowserWindow, session } from "electron";
import { logger } from "../utils/logger";
import {
  ARTIFACT_PREVIEW_KIND,
  hardenGuestPreferences,
  isolateGuestSession,
  lockDownGuest,
  SKETCHPAD_KIND,
} from "./sandboxed-webviews";

const log = logger.scope("sandboxed webviews");
const WEBVIEW_KINDS = [SKETCHPAD_KIND, ARTIFACT_PREVIEW_KIND];

export function setupArtifactPreviewWebviews(window: BrowserWindow): void {
  const preloadPath = path.join(__dirname, "preload.js");
  window.webContents.on("will-attach-webview", (event, preferences, params) => {
    const kind = WEBVIEW_KINDS.find((candidate) =>
      candidate.matches(params.src, params.partition),
    );
    if (!kind) {
      event.preventDefault();
      log.warn("Blocked an unsupported webview attachment");
      return;
    }
    hardenGuestPreferences(preferences, preloadPath, kind);
  });
  window.webContents.on("did-attach-webview", (_event, guest) => {
    const kind =
      guest.session === session.fromPartition(SKETCHPAD_PARTITION)
        ? SKETCHPAD_KIND
        : ARTIFACT_PREVIEW_KIND;
    lockDownGuest(guest, kind);
    if (kind === ARTIFACT_PREVIEW_KIND) isolateGuestSession(guest.session);
  });
}
