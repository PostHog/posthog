import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { QuickAskAttachment } from "@posthog/quick-ask/service/quick-ask";
import {
  BrowserWindow,
  type Display,
  desktopCapturer,
  ipcMain,
  screen,
  shell,
  systemPreferences,
} from "electron";
import {
  QUICK_ASK_ANNOTATE_DONE_CHANNEL,
  QUICK_ASK_ANNOTATE_SHOT_CHANNEL,
  QUICK_ASK_ANNOTATE_WINDOW_ARG,
  QUICK_ASK_ATTACHMENT_CHANNEL,
  QUICK_ASK_SCREEN_SETTINGS_CHANNEL,
  type QuickAskAttachmentPayload,
} from "../shared/constants";
import { isDevBuild } from "./utils/env";
import { logger } from "./utils/logger";

const log = logger.scope("quick-ask");

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const VITE_DEV_SERVER_URL = process.env.ELECTRON_RENDERER_URL;
/** Lets the e2e run without a screen: a PNG file stands in for the capture. */
const FAKE_CAPTURE_ENV = "QUICK_ASK_FAKE_CAPTURE";
/** Compositor settle time between hiding the panel and grabbing the frame. */
const HIDE_SETTLE_MS = 220;

let annotateWindow: BrowserWindow | null = null;
/** Raw shot handed to the annotator, held until it exports or cancels. */
let shotDataUrl: string | null = null;
let pending: QuickAskAttachment | null = null;
let handlersRegistered = false;
/** Windows the app is tearing down itself, so `closed` skips the OS-close
 * cleanup (done handler, reopen, teardown all go through closeAnnotator). */
const appInitiatedClose = new WeakSet<BrowserWindow>();

interface CaptureHost {
  getPanel(): BrowserWindow | null;
  showPanel(): void;
  hidePanel(): void;
}

export function pendingAttachments(): QuickAskAttachment[] {
  return pending ? [pending] : [];
}

export function clearPendingAttachment(host?: CaptureHost): void {
  pending = null;
  if (host) sendAttachment(host, { previewDataUrl: null });
}

function sendAttachment(
  host: CaptureHost,
  payload: QuickAskAttachmentPayload,
): void {
  const panel = host.getPanel();
  if (panel && !panel.isDestroyed()) {
    panel.webContents.send(QUICK_ASK_ATTACHMENT_CHANNEL, payload);
  }
}

async function grabScreen(display: Display): Promise<string | null> {
  const fakePath = process.env[FAKE_CAPTURE_ENV];
  if (fakePath) {
    const bytes = await readFile(fakePath);
    return `data:image/png;base64,${bytes.toString("base64")}`;
  }
  // Ask before checking consent: this call is what registers the app in the
  // macOS Screen Recording list and fires the consent prompt on first use
  // (askForMediaAccess does not support "screen").
  const sources = await desktopCapturer.getSources({
    types: ["screen"],
    thumbnailSize: {
      width: Math.round(display.size.width * display.scaleFactor),
      height: Math.round(display.size.height * display.scaleFactor),
    },
  });
  if (
    process.platform === "darwin" &&
    systemPreferences.getMediaAccessStatus("screen") !== "granted"
  ) {
    return null;
  }
  const source =
    sources.find((s) => s.display_id === String(display.id)) ?? sources[0];
  if (!source || source.thumbnail.isEmpty()) return null;
  return source.thumbnail.toDataURL();
}

function openAnnotator(display: Display, host: CaptureHost): void {
  closeAnnotator();
  const window = new BrowserWindow({
    ...display.bounds,
    show: false,
    frame: false,
    resizable: false,
    movable: false,
    fullscreenable: false,
    skipTaskbar: true,
    hiddenInMissionControl: true,
    backgroundColor: "#101014",
    ...(process.platform === "darwin" ? { type: "panel" as const } : {}),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, "preload.js"),
      additionalArguments: [QUICK_ASK_ANNOTATE_WINDOW_ARG],
    },
  });
  window.setAlwaysOnTop(true, "screen-saver");
  window.on("closed", () => {
    if (annotateWindow === window) annotateWindow = null;
    // A close the app did not initiate (Alt+F4, the window menu's Close) never
    // ran the done handler, so drop the held capture and re-show the panel the
    // capture flow hid — otherwise the panel looks gone until the next summon.
    if (appInitiatedClose.delete(window)) return;
    shotDataUrl = null;
    host.showPanel();
  });
  if (VITE_DEV_SERVER_URL) {
    void window.loadURL(`${VITE_DEV_SERVER_URL}/quick-ask-annotate.html`);
  } else {
    void window.loadFile(
      path.join(__dirname, "../renderer/main_window/quick-ask-annotate.html"),
    );
  }
  window.once("ready-to-show", () => {
    window.show();
    window.focus();
  });
  annotateWindow = window;
}

function closeAnnotator(): void {
  if (annotateWindow && !annotateWindow.isDestroyed()) {
    appInitiatedClose.add(annotateWindow);
    annotateWindow.destroy();
  }
  annotateWindow = null;
}

/** Hides the panel, freezes the screen it is on, opens the annotator. */
export async function beginCapture(host: CaptureHost): Promise<void> {
  const panel = host.getPanel();
  // Match the whole panel rect, not just its top-left point: a panel dragged
  // across a display edge can straddle two, and the corner may sit on the
  // display holding the smaller part. getDisplayMatching picks the display
  // with the largest overlap. No panel means summon-at-cursor never ran, so
  // fall back to the cursor's display.
  const display =
    panel && !panel.isDestroyed()
      ? screen.getDisplayMatching(panel.getBounds())
      : screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  host.hidePanel();
  await new Promise((resolve) => setTimeout(resolve, HIDE_SETTLE_MS));
  let dataUrl: string | null = null;
  try {
    dataUrl = await grabScreen(display);
  } catch (error) {
    log.warn("Quick ask screen capture failed", { error });
  }
  if (!dataUrl && process.platform === "darwin") {
    // "denied" with the app toggled on in System Settings usually means the
    // grant sits on the wrong identity: dev runs launched from a terminal
    // are attributed to the terminal (the responsible process).
    log.warn("Quick ask screen capture unavailable", {
      mediaAccessStatus: systemPreferences.getMediaAccessStatus("screen"),
    });
  }
  if (!dataUrl) {
    host.showPanel();
    // Dev runs are the stock Electron binary; macOS attributes the consent
    // to "Electron", and a version bump invalidates it (new code identity).
    const consentIdentity = isDevBuild() ? "Electron" : "PostHog";
    sendAttachment(
      host,
      process.platform === "darwin"
        ? {
            previewDataUrl: null,
            error: `Grant screen recording to ${consentIdentity}, then relaunch.`,
            canOpenSettings: true,
          }
        : { previewDataUrl: null, error: "Screen capture failed." },
    );
    return;
  }
  shotDataUrl = dataUrl;
  openAnnotator(display, host);
}

/** Events must come from the named window: these ipcMain channels are shared
 * by every renderer, and only the annotator may read or submit the held
 * screenshot, only the panel may open system settings. */
function fromWindow(
  event: { sender: Electron.WebContents },
  window: BrowserWindow | null,
): boolean {
  return (
    window !== null &&
    !window.isDestroyed() &&
    event.sender === window.webContents
  );
}

export function setupQuickAskCapture(host: CaptureHost): void {
  if (handlersRegistered) return;
  handlersRegistered = true;
  ipcMain.handle(QUICK_ASK_ANNOTATE_SHOT_CHANNEL, (event) =>
    fromWindow(event, annotateWindow) ? shotDataUrl : null,
  );
  ipcMain.on(QUICK_ASK_SCREEN_SETTINGS_CHANNEL, (event) => {
    if (!fromWindow(event, host.getPanel())) return;
    void shell.openExternal(
      "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    );
  });
  ipcMain.on(QUICK_ASK_ANNOTATE_DONE_CHANNEL, (event, result: unknown) => {
    if (!fromWindow(event, annotateWindow)) return;
    shotDataUrl = null;
    closeAnnotator();
    host.showPanel();
    const dataUrl = (result as { dataUrl?: unknown } | null)?.dataUrl;
    if (typeof dataUrl !== "string") return;
    const base64 = dataUrl.split(",")[1];
    if (!base64) return;
    pending = { name: "screenshot.png", base64, mimeType: "image/png" };
    sendAttachment(host, { previewDataUrl: dataUrl });
  });
}

export function teardownQuickAskCapture(): void {
  closeAnnotator();
  shotDataUrl = null;
  pending = null;
}
