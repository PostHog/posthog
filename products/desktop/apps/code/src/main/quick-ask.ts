import path from "node:path";
import { fileURLToPath } from "node:url";
import { TASK_LINK_SERVICE } from "@posthog/core/links/identifiers";
import type { TaskLinkService } from "@posthog/core/links/task-link";
import {
  QUICK_ASK_SERVICE,
  type QuickAskService,
} from "@posthog/core/quick-ask/quick-ask";
import {
  isQuickAskShortcut,
  QUICK_ASK_DEFAULT_SHORTCUT,
} from "@posthog/shared/quick-ask-shortcuts";
import { app, BrowserWindow, globalShortcut, ipcMain, screen } from "electron";
import {
  QUICK_ASK_ASK_CHANNEL,
  QUICK_ASK_CANCEL_CHANNEL,
  QUICK_ASK_DRAG_END_CHANNEL,
  QUICK_ASK_DRAG_START_CHANNEL,
  QUICK_ASK_EVENT_CHANNEL,
  QUICK_ASK_HIDE_CHANNEL,
  QUICK_ASK_LAYOUT_CHANNEL,
  QUICK_ASK_OPEN_IN_APP_CHANNEL,
  QUICK_ASK_RESET_CHANNEL,
  QUICK_ASK_RESIZE_CHANNEL,
  QUICK_ASK_SHOWN_CHANNEL,
  QUICK_ASK_WINDOW_ARG,
  type QuickAskDragStartPayload,
  type QuickAskLayoutPayload,
  type QuickAskResizePayload,
} from "../shared/constants";
import { container } from "./di/container";
import {
  computeGeometry,
  PILL_HEIGHT,
  PILL_TOP_TO_WINDOW_BOTTOM,
  PILL_TOP_TO_WINDOW_TOP,
  SCREEN_MARGIN,
} from "./quick-ask-geometry";
import { isDevBuild } from "./utils/env";
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
  enabled: boolean;
  shortcut: string;
  /** False when another app owns the accelerator. */
  registered: boolean;
}

let quickAskEnabled = false;
let currentShortcut: string = QUICK_ASK_DEFAULT_SHORTCUT;
let shortcutRegistered = false;

function registerShortcut(accelerator: string): boolean {
  if (shortcutRegistered) {
    globalShortcut.unregister(currentShortcut);
    shortcutRegistered = false;
  }
  const registered = globalShortcut.register(accelerator, toggleQuickAsk);
  if (registered) {
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
    shortcut: currentShortcut,
    registered: shortcutRegistered,
  };
}

export function setQuickAskShortcut(accelerator: string): QuickAskState {
  if (!quickAskEnabled || !isQuickAskShortcut(accelerator)) {
    return getQuickAskState();
  }
  const registered = registerShortcut(accelerator);
  if (registered) {
    quickAskStore.set("shortcut", accelerator);
  }
  // On failure `currentShortcut` keeps the last working accelerator; report
  // the requested one so the settings UI can show it is taken.
  return { enabled: true, shortcut: accelerator, registered };
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let quickAskWindow: BrowserWindow | null = null;

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

  // Answer rendering fetches live data over the host tRPC bridge.
  attachWindowToTrpc(window);

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

/** Last logged decision; geometry logs only when the decision changes. */
let lastGeometryLogKey = "";

function applyGeometry(window: BrowserWindow, why: string): void {
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
  // Log every decision change so placement bugs are debuggable from the
  // field (main.log), without spamming a line per streamed token.
  const clamped = content.height > geometry.maxHeight;
  const logKey = `${geometry.flip}|${clamped}|${why === "summon"}`;
  if (why === "summon" || logKey !== lastGeometryLogKey) {
    lastGeometryLogKey = logKey;
    log.info("Quick ask geometry", {
      why,
      anchor,
      content,
      flip: geometry.flip,
      clamped,
      maxHeight: geometry.maxHeight,
      bounds: {
        x: geometry.x,
        y: geometry.y,
        width: geometry.width,
        height: geometry.height,
      },
      workArea: area,
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
  applyGeometry(window, "summon");
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
  try {
    for await (const event of getQuickAskService().ask({
      question,
      conversationId,
    })) {
      if (event.type === "error") {
        log.warn("Quick ask answered with an error", {
          message: event.message,
          detail: event.detail,
        });
      }
      if (event.type === "trace") {
        log.info("Quick ask stream trace", { detail: event.detail });
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
  if (quickAskWindow && !quickAskWindow.isDestroyed()) {
    quickAskWindow.destroy();
  }
  quickAskWindow = null;
}

export function setupQuickAsk(): void {
  // Prototype: dev builds only, or explicit opt-in.
  if (!isDevBuild() && process.env.POSTHOG_QUICK_ASK !== "1") {
    return;
  }
  quickAskEnabled = true;

  ipcMain.on(QUICK_ASK_HIDE_CHANNEL, () => hideQuickAsk());
  ipcMain.on(QUICK_ASK_RESIZE_CHANNEL, (_event, size: unknown) => {
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
    applyGeometry(quickAskWindow, "content");
  });
  // Dragging: native `-webkit-app-region: drag` is incompatible with the
  // forwarded click-through events, so the renderer reports a grab offset
  // and the main process follows the cursor.
  ipcMain.on(QUICK_ASK_DRAG_START_CHANNEL, (_event, offset: unknown) => {
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
  ipcMain.on(QUICK_ASK_DRAG_END_CHANNEL, () => {
    stopDrag();
    if (quickAskWindow && !quickAskWindow.isDestroyed()) {
      applyGeometry(quickAskWindow, "drag-end");
    }
  });
  ipcMain.on(QUICK_ASK_OPEN_IN_APP_CHANNEL, () => {
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
    (_event, question: unknown, conversationId: unknown) => {
      if (typeof question !== "string" || !question.trim()) return;
      void streamAnswer(
        question.trim(),
        typeof conversationId === "string" && conversationId
          ? conversationId
          : undefined,
      );
    },
  );
  ipcMain.on(QUICK_ASK_CANCEL_CHANNEL, () => {
    getQuickAskService().cancel();
  });
  ipcMain.on(QUICK_ASK_RESET_CHANNEL, () => {
    const service = getQuickAskService();
    service.reset();
    void service.warm();
  });

  const stored = quickAskStore.get("shortcut");
  const preferred =
    stored && isQuickAskShortcut(stored) ? stored : QUICK_ASK_DEFAULT_SHORTCUT;
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
  quickAskWindow = createQuickAskWindow();

  app.on("will-quit", () => {
    if (shortcutRegistered) {
      globalShortcut.unregister(currentShortcut);
    }
  });
}
