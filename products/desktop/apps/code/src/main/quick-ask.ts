import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { TASK_LINK_SERVICE } from "@posthog/core/links/identifiers";
import type { TaskLinkService } from "@posthog/core/links/task-link";
import {
  computeGeometry,
  PILL_HEIGHT,
  PILL_TOP_TO_WINDOW_BOTTOM,
  PILL_TOP_TO_WINDOW_TOP,
  SCREEN_MARGIN,
} from "@posthog/quick-ask/geometry/geometry";
import { ShakeDetector } from "@posthog/quick-ask/gesture/shake";
import {
  QUICK_ASK_SERVICE,
  type QuickAskService,
} from "@posthog/quick-ask/service/quick-ask";
import {
  isValidQuickAskAccelerator,
  QUICK_ASK_DEFAULT_SHORTCUT,
} from "@posthog/shared/quick-ask-shortcuts";
import { app, BrowserWindow, globalShortcut, ipcMain, screen } from "electron";
import {
  QUICK_ASK_ASK_CHANNEL,
  QUICK_ASK_CANCEL_CHANNEL,
  QUICK_ASK_CAPTURE_CHANNEL,
  QUICK_ASK_DISCARD_ATTACHMENT_CHANNEL,
  QUICK_ASK_DRAG_END_CHANNEL,
  QUICK_ASK_DRAG_START_CHANNEL,
  QUICK_ASK_EVENT_CHANNEL,
  QUICK_ASK_HIDE_CHANNEL,
  QUICK_ASK_LAYOUT_CHANNEL,
  QUICK_ASK_OPEN_IN_APP_CHANNEL,
  QUICK_ASK_RESET_CHANNEL,
  QUICK_ASK_RESIZE_CHANNEL,
  QUICK_ASK_SHAKE_CHANNEL,
  QUICK_ASK_SHOWN_CHANNEL,
  QUICK_ASK_WINDOW_ARG,
  type QuickAskDragStartPayload,
  type QuickAskLayoutPayload,
  type QuickAskResizePayload,
} from "../shared/constants";
import { container } from "./di/container";
import { setupExternalLinkHandlers } from "./external-links";
import {
  beginCapture,
  clearPendingAttachment,
  pendingAttachments,
  setupQuickAskCapture,
  teardownQuickAskCapture,
} from "./quick-ask-capture";
import { logger } from "./utils/logger";
import { quickAskStore } from "./utils/store";
import { attachWindowToTrpc, focusMainWindow } from "./window";

const log = logger.scope("quick-ask");

const QUICK_ASK_VITE_DEV_SERVER_URL = process.env.ELECTRON_RENDERER_URL;
const QUICK_ASK_VITE_NAME = "main_window";

// The window's bounds always hug the visible content (the reliable way to
// run a floating widget: anything outside the pill and card is simply not
// part of the window, so clicks land on whatever is behind with no
// click-through juggling). Width starts at the empty pill row and follows
// the renderer's measurements, capped here.
const PANEL_MAX_WIDTH = 640;
const PANEL_INITIAL_WIDTH = 300;
const PANEL_INITIAL_HEIGHT = PILL_HEIGHT;
// Where the cursor lands inside the window: on the hedgehog, Figma-style.
const CURSOR_IN_WINDOW_X = 55;
const CURSOR_IN_WINDOW_X_OFFSET = 8;
const CURSOR_ABOVE_PILL_PX = 10;
/** Last geometry the renderer reported; reused across hides/shows. */
let cachedContentHeight = PANEL_INITIAL_HEIGHT;
let cachedContentWidth = PANEL_INITIAL_WIDTH;
/** Whether the current layout has the card above the pill. */
let currentFlip = false;
/**
 * The pill row's top-left corner in screen coordinates — the single fixed
 * point every other placement value derives from. Planted at summon,
 * carried along by dragging.
 */
let pillAnchor: { x: number; y: number } | null = null;

type QuickAskDragState = {
  dx: number;
  dy: number;
  timer: NodeJS.Timeout;
};
let dragState: QuickAskDragState | null = null;

export interface QuickAskState {
  /** The panel exists in this build. */
  enabled: boolean;
  /** The user toggle; off unregisters the shortcut and drops the window. */
  active: boolean;
  shortcut: string;
  /** False when another app owns the accelerator. */
  registered: boolean;
  /** Space new threads file into; empty means the personal space. */
  defaultChannelId: string;
  defaultRepositories: string[];
  defaultGithubIntegrationId: number;
  /** Empty strings follow the adapter/model defaults. */
  defaultAdapter: string;
  defaultModel: string;
  defaultEffort: string;
}

export interface QuickAskSettingsPatch {
  active?: boolean;
  defaultChannelId?: string;
  defaultRepositories?: string[];
  defaultGithubIntegrationId?: number;
  defaultAdapter?: string;
  defaultModel?: string;
  defaultEffort?: string;
}

let quickAskEnabled = false;
let currentShortcut: string = QUICK_ASK_DEFAULT_SHORTCUT;
let shortcutRegistered = false;

function registerShortcut(accelerator: string): boolean {
  // Re-recording the accelerator that is already live is a no-op, not a change.
  if (shortcutRegistered && accelerator === currentShortcut) {
    return true;
  }
  // Register the replacement before releasing the old one, so a rejected
  // accelerator (owned by another app) leaves the working shortcut intact.
  const registered = globalShortcut.register(accelerator, toggleQuickAsk);
  if (registered) {
    if (shortcutRegistered) {
      globalShortcut.unregister(currentShortcut);
    }
    currentShortcut = accelerator;
    shortcutRegistered = true;
    log.info("Quick ask shortcut registered", { shortcut: accelerator });
  } else {
    log.warn("Quick ask shortcut is taken by another app", {
      shortcut: accelerator,
    });
  }
  return registered;
}

export function getQuickAskState(): QuickAskState {
  return {
    enabled: quickAskEnabled,
    active: quickAskStore.get("panelEnabled"),
    shortcut: currentShortcut,
    registered: shortcutRegistered,
    defaultChannelId: quickAskStore.get("defaultChannelId"),
    defaultRepositories: quickAskStore.get("defaultRepositories"),
    defaultGithubIntegrationId: quickAskStore.get("defaultGithubIntegrationId"),
    defaultAdapter: quickAskStore.get("defaultAdapter"),
    defaultModel: quickAskStore.get("defaultModel"),
    defaultEffort: quickAskStore.get("defaultEffort"),
  };
}

export function setQuickAskSettings(
  patch: QuickAskSettingsPatch,
): QuickAskState {
  if (patch.active !== undefined && quickAskEnabled) {
    quickAskStore.set("panelEnabled", patch.active);
    if (patch.active) {
      activateQuickAsk();
    } else {
      deactivateQuickAsk();
    }
  }
  if (patch.defaultChannelId !== undefined) {
    quickAskStore.set("defaultChannelId", patch.defaultChannelId);
  }
  if (patch.defaultRepositories !== undefined) {
    quickAskStore.set("defaultRepositories", patch.defaultRepositories);
  }
  if (patch.defaultGithubIntegrationId !== undefined) {
    quickAskStore.set(
      "defaultGithubIntegrationId",
      patch.defaultGithubIntegrationId,
    );
  }
  if (patch.defaultAdapter !== undefined) {
    quickAskStore.set("defaultAdapter", patch.defaultAdapter);
  }
  if (patch.defaultModel !== undefined) {
    quickAskStore.set("defaultModel", patch.defaultModel);
  }
  if (patch.defaultEffort !== undefined) {
    quickAskStore.set("defaultEffort", patch.defaultEffort);
  }
  return getQuickAskState();
}

export function setQuickAskShortcut(accelerator: string): QuickAskState {
  if (!quickAskEnabled || !isValidQuickAskAccelerator(accelerator)) {
    return getQuickAskState();
  }
  if (!quickAskStore.get("panelEnabled")) {
    quickAskStore.set("shortcut", accelerator);
    currentShortcut = accelerator;
    return getQuickAskState();
  }
  const registered = registerShortcut(accelerator);
  if (registered) {
    quickAskStore.set("shortcut", accelerator);
  }
  // On failure the old accelerator stays registered and `currentShortcut`
  // keeps its name; report the requested one so the settings UI can show it
  // is taken.
  return { ...getQuickAskState(), shortcut: accelerator, registered };
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let quickAskWindow: BrowserWindow | null = null;

/**
 * The only host tRPC routes the panel renderer may call: auth state and
 * tokens for its PostHog API client, and opening vetted external links.
 * Everything else on the router (shell, fs, secureStore, git…) stays
 * unreachable from this window even if its renderer is compromised.
 */
const QUICK_ASK_TRPC_ROUTES = new Set([
  "auth.getState",
  "auth.onStateChanged",
  "auth.getValidAccessToken",
  "auth.refreshAccessToken",
  "os.openExternal",
]);

function createQuickAskWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: PANEL_INITIAL_WIDTH,
    height: PANEL_INITIAL_HEIGHT,
    show: false,
    frame: false,
    transparent: true,
    backgroundColor: "#00000000",
    // The content draws its own shadows; the native shadow would outline the
    // whole (mostly empty) window rectangle.
    hasShadow: false,
    resizable: false,
    maximizable: false,
    minimizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    hiddenInMissionControl: true,
    // On macOS this applies NSWindowStyleMaskNonactivatingPanel behavior:
    // the panel takes keyboard input without activating the app, so the app
    // the user was in stays visually frontmost (fixed in Electron >= 30).
    ...(process.platform === "darwin" ? { type: "panel" as const } : {}),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, "preload.js"),
      // Shares the app session so a future real PostHog AI wiring is already
      // authenticated.
      partition: "persist:main",
      additionalArguments: [QUICK_ASK_WINDOW_ARG],
    },
  });

  // Answer rendering fetches live data over the host tRPC bridge, narrowed
  // to the auth-token and external-link routes the panel actually uses.
  attachWindowToTrpc(window, (path) => QUICK_ASK_TRPC_ROUTES.has(path));

  // The panel shares the app session and its privileged preload bridges, so
  // it gets the same navigation boundary as the main window: links open in
  // the external browser and the window itself never leaves its own page —
  // an in-place navigation would carry the bridges into a foreign origin.
  const quickAskHome = QUICK_ASK_VITE_DEV_SERVER_URL
    ? new URL(`${QUICK_ASK_VITE_DEV_SERVER_URL}/quick-ask.html`)
    : pathToFileURL(
        path.join(
          __dirname,
          `../renderer/${QUICK_ASK_VITE_NAME}/quick-ask.html`,
        ),
      );
  setupExternalLinkHandlers(window, quickAskHome);

  window.setAlwaysOnTop(true, "screen-saver");
  // macOS: a `panel` window already floats over full-screen apps on every
  // Space. Do NOT call setVisibleOnAllWorkspaces with visibleOnFullScreen:
  // it flips the app's activation policy to accessory, which removes the app
  // from the Dock and the Cmd+Tab switcher.
  if (process.platform !== "darwin") {
    window.setVisibleOnAllWorkspaces(true);
  }
  window.on("closed", () => {
    quickAskWindow = null;
  });

  if (QUICK_ASK_VITE_DEV_SERVER_URL) {
    void window.loadURL(`${QUICK_ASK_VITE_DEV_SERVER_URL}/quick-ask.html`);
  } else {
    void window.loadFile(
      path.join(__dirname, `../renderer/${QUICK_ASK_VITE_NAME}/quick-ask.html`),
    );
  }

  return window;
}

function applyGeometry(window: BrowserWindow): void {
  if (window.isDestroyed()) return;
  const bounds = window.getBounds();
  const anchor = pillAnchor ?? {
    x: bounds.x,
    y: bounds.y + PILL_TOP_TO_WINDOW_TOP,
  };
  const area = screen.getDisplayNearestPoint(anchor).workArea;
  const content = { width: cachedContentWidth, height: cachedContentHeight };
  const geometry = computeGeometry(anchor, content, area, currentFlip);
  currentFlip = geometry.flip;
  if (
    geometry.x !== bounds.x ||
    geometry.y !== bounds.y ||
    geometry.width !== bounds.width ||
    geometry.height !== bounds.height
  ) {
    window.setBounds({
      x: geometry.x,
      y: geometry.y,
      width: geometry.width,
      height: geometry.height,
    });
  }
  const payload: QuickAskLayoutPayload = {
    flip: geometry.flip,
    maxHeight: geometry.maxHeight,
  };
  window.webContents.send(QUICK_ASK_LAYOUT_CHANNEL, payload);
}

function stopDrag(): void {
  if (dragState) {
    clearInterval(dragState.timer);
    dragState = null;
  }
}

/**
 * Summon: plant the pill anchor so the cursor lands on the hedgehog's nose
 * (Figma cursor-chat style); `applyGeometry` derives everything else.
 */
function summonAtCursor(window: BrowserWindow): void {
  const cursor = screen.getCursorScreenPoint();
  const area = screen.getDisplayNearestPoint(cursor).workArea;
  const x = Math.round(
    Math.min(
      Math.max(
        cursor.x + CURSOR_IN_WINDOW_X_OFFSET - CURSOR_IN_WINDOW_X,
        area.x + SCREEN_MARGIN,
      ),
      area.x + area.width - PANEL_MAX_WIDTH - SCREEN_MARGIN,
    ),
  );
  pillAnchor = { x, y: Math.round(cursor.y + CURSOR_ABOVE_PILL_PX) };
  // Fresh summon, fresh direction decision.
  currentFlip = false;
  applyGeometry(window);
}

function showQuickAsk(): void {
  if (!quickAskWindow || quickAskWindow.isDestroyed()) {
    quickAskWindow = createQuickAskWindow();
  }
  summonAtCursor(quickAskWindow);
  quickAskWindow.show();
  quickAskWindow.focus();
  quickAskWindow.webContents.send(QUICK_ASK_SHOWN_CHANNEL);
  // Boot a sandbox while the user types.
  void getQuickAskService().warm();
}

function hideQuickAsk(): void {
  // The stream keeps running while hidden so reopening restores the finished
  // answer; it is only cancelled by a new question or app quit.
  stopDrag();
  if (!quickAskWindow || quickAskWindow.isDestroyed()) return;
  if (!quickAskWindow.isVisible()) return;
  quickAskWindow.hide();
}

function getQuickAskService(): QuickAskService {
  return container.get<QuickAskService>(QUICK_ASK_SERVICE);
}

const captureHost = {
  getPanel: (): BrowserWindow | null => quickAskWindow,
  showPanel: (): void => {
    if (quickAskWindow && !quickAskWindow.isDestroyed()) {
      quickAskWindow.show();
      quickAskWindow.focus();
    }
  },
  hidePanel: (): void => hideQuickAsk(),
};

/** Streams one PostHog AI turn, forwarding each event to the panel. */
async function streamAnswer(
  question: string,
  conversationId: string | undefined,
): Promise<void> {
  const target = quickAskWindow;
  if (!target || target.isDestroyed()) return;
  const send = (event: unknown): void => {
    if (!target.isDestroyed()) {
      target.webContents.send(QUICK_ASK_EVENT_CHANNEL, event);
    }
  };
  const attachments = pendingAttachments();
  clearPendingAttachment(captureHost);
  try {
    for await (const event of getQuickAskService().ask({
      question,
      conversationId,
      attachments,
    })) {
      if (event.type === "error") {
        log.warn("Quick ask answered with an error", {
          message: event.message,
          detail: event.detail,
        });
      }
      send(event);
    }
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return; // Cancelled: a newer question or the panel hid.
    }
    log.warn("Quick ask stream failed", { error });
    send({
      type: "error",
      message: "PostHog AI is unavailable right now. Try again.",
    });
  }
}

export function toggleQuickAsk(): void {
  if (
    quickAskWindow &&
    !quickAskWindow.isDestroyed() &&
    quickAskWindow.isVisible()
  ) {
    hideQuickAsk();
  } else {
    showQuickAsk();
  }
}

/** Tear down the panel so `window-all-closed` app-quit behavior is preserved. */
export function destroyQuickAskWindow(): void {
  stopDrag();
  teardownQuickAskCapture();
  if (quickAskWindow && !quickAskWindow.isDestroyed()) {
    quickAskWindow.destroy();
  }
  quickAskWindow = null;
}

function activateQuickAsk(): void {
  const stored = quickAskStore.get("shortcut");
  const preferred =
    stored && isValidQuickAskAccelerator(stored)
      ? stored
      : QUICK_ASK_DEFAULT_SHORTCUT;
  let registered = registerShortcut(preferred);
  // The default may be taken (Option+Space is popular); fall back so the
  // feature still works until the user picks another one in settings.
  if (!registered && preferred !== "CommandOrControl+Shift+Space") {
    registered = registerShortcut("CommandOrControl+Shift+Space");
  }
  if (!registered) {
    currentShortcut = preferred;
  }
  // Pre-create hidden so the first summon is instant.
  if (!quickAskWindow || quickAskWindow.isDestroyed()) {
    quickAskWindow = createQuickAskWindow();
  }
}

function deactivateQuickAsk(): void {
  if (shortcutRegistered) {
    globalShortcut.unregister(currentShortcut);
    shortcutRegistered = false;
  }
  destroyQuickAskWindow();
}

/**
 * Every window shares these ipcMain channels, so each handler accepts events
 * only from the panel's own webContents — no other renderer (main window,
 * webviews, or a hypothetically compromised frame) may drive the panel's
 * privileged surface (asking, capture, window placement).
 */
function fromPanel(event: Electron.IpcMainEvent): boolean {
  return (
    quickAskWindow !== null &&
    !quickAskWindow.isDestroyed() &&
    event.sender === quickAskWindow.webContents
  );
}

export function setupQuickAsk(): void {
  quickAskEnabled = true;

  ipcMain.on(QUICK_ASK_HIDE_CHANNEL, (event) => {
    if (!fromPanel(event)) return;
    hideQuickAsk();
  });
  ipcMain.on(QUICK_ASK_RESIZE_CHANNEL, (event, size: unknown) => {
    if (!fromPanel(event)) return;
    if (!quickAskWindow || quickAskWindow.isDestroyed()) return;
    const { width, height } = (size ?? {}) as Partial<QuickAskResizePayload>;
    if (typeof width !== "number" || !Number.isFinite(width)) {
      log.warn("Quick ask resize payload malformed", { size });
      return;
    }
    if (typeof height !== "number" || !Number.isFinite(height)) {
      log.warn("Quick ask resize payload malformed", { size });
      return;
    }
    cachedContentWidth = Math.min(
      PANEL_MAX_WIDTH,
      Math.max(PANEL_INITIAL_WIDTH, Math.round(width)),
    );
    cachedContentHeight = Math.max(PILL_HEIGHT, Math.round(height));
    applyGeometry(quickAskWindow);
  });
  // Dragging: native `-webkit-app-region: drag` is incompatible with the
  // forwarded click-through events, so the renderer reports a grab offset
  // and the main process follows the cursor.
  ipcMain.on(QUICK_ASK_DRAG_START_CHANNEL, (event, offset: unknown) => {
    if (!fromPanel(event)) return;
    if (!quickAskWindow || quickAskWindow.isDestroyed()) return;
    const { dx, dy } = (offset ?? {}) as Partial<QuickAskDragStartPayload>;
    if (
      typeof dx !== "number" ||
      typeof dy !== "number" ||
      !Number.isFinite(dx) ||
      !Number.isFinite(dy)
    ) {
      return;
    }
    stopDrag();
    const shakeDetector = new ShakeDetector();
    dragState = {
      dx,
      dy,
      timer: setInterval(() => {
        if (
          !quickAskWindow ||
          quickAskWindow.isDestroyed() ||
          !quickAskWindow.isVisible()
        ) {
          stopDrag();
          return;
        }
        const point = screen.getCursorScreenPoint();
        if (shakeDetector.sample(point.x, Date.now())) {
          quickAskWindow.webContents.send(QUICK_ASK_SHAKE_CHANNEL);
        }
        const bounds = quickAskWindow.getBounds();
        const x = Math.round(point.x - dx);
        const y = Math.round(point.y - dy);
        if (x !== bounds.x || y !== bounds.y) {
          quickAskWindow.setPosition(x, y);
          // The anchor rides along; the grow direction is re-decided once
          // at drag end, so the panel does not flip mid-drag.
          pillAnchor = {
            x,
            y: currentFlip
              ? y + bounds.height - PILL_TOP_TO_WINDOW_BOTTOM
              : y + PILL_TOP_TO_WINDOW_TOP,
          };
        }
      }, 15),
    };
  });
  ipcMain.on(QUICK_ASK_DRAG_END_CHANNEL, (event) => {
    if (!fromPanel(event)) return;
    stopDrag();
    if (quickAskWindow && !quickAskWindow.isDestroyed()) {
      applyGeometry(quickAskWindow);
    }
  });
  ipcMain.on(QUICK_ASK_OPEN_IN_APP_CHANNEL, (event) => {
    if (!fromPanel(event)) return;
    hideQuickAsk();
    // The thread is a task; land the main window on it.
    const taskId = getQuickAskService().currentTaskId;
    if (taskId) {
      container.get<TaskLinkService>(TASK_LINK_SERVICE).openTask({ taskId });
    }
    focusMainWindow("quick-ask-open-in-app");
    app.focus({ steal: true });
  });
  ipcMain.on(
    QUICK_ASK_ASK_CHANNEL,
    (event, question: unknown, conversationId: unknown) => {
      if (!fromPanel(event)) return;
      if (typeof question !== "string" || !question.trim()) return;
      void streamAnswer(
        question.trim(),
        typeof conversationId === "string" && conversationId
          ? conversationId
          : undefined,
      );
    },
  );
  ipcMain.on(QUICK_ASK_CANCEL_CHANNEL, (event) => {
    if (!fromPanel(event)) return;
    getQuickAskService().cancel();
  });
  ipcMain.on(QUICK_ASK_RESET_CHANNEL, (event) => {
    if (!fromPanel(event)) return;
    clearPendingAttachment(captureHost);
    const service = getQuickAskService();
    service.reset();
    void service.warm();
  });
  ipcMain.on(QUICK_ASK_CAPTURE_CHANNEL, (event) => {
    if (!fromPanel(event)) return;
    void beginCapture(captureHost);
  });
  ipcMain.on(QUICK_ASK_DISCARD_ATTACHMENT_CHANNEL, (event) => {
    if (!fromPanel(event)) return;
    clearPendingAttachment(captureHost);
  });
  setupQuickAskCapture(captureHost);

  if (quickAskStore.get("panelEnabled")) {
    activateQuickAsk();
  }

  app.on("will-quit", () => {
    if (shortcutRegistered) {
      globalShortcut.unregister(currentShortcut);
    }
  });
}
