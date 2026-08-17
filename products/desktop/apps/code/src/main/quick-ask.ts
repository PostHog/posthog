import path from "node:path";
import { fileURLToPath } from "node:url";
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
  QUICK_ASK_RESIZE_CHANNEL,
  QUICK_ASK_SET_INTERACTIVE_CHANNEL,
  QUICK_ASK_SHOWN_CHANNEL,
  QUICK_ASK_WINDOW_ARG,
} from "../shared/constants";
import { container } from "./di/container";
import { isDevBuild } from "./utils/env";
import { logger } from "./utils/logger";
import { quickAskStore } from "./utils/store";
import { focusMainWindow } from "./window";

const log = logger.scope("quick-ask");

const QUICK_ASK_VITE_DEV_SERVER_URL = process.env.ELECTRON_RENDERER_URL;
const QUICK_ASK_VITE_NAME = "main_window";

const PANEL_WIDTH = 640;
// Layout constants matching quick-ask.css: root padding top/bottom 10/14,
// pill row 46px, card gap 10px. Non-card chrome is 80px of window height.
const ROOT_PAD_TOP = 10;
const ROOT_PAD_BOTTOM = 14;
const PILL_ROW_HEIGHT = 46;
const CARD_GAP = 10;
const CHROME_HEIGHT =
  ROOT_PAD_TOP + PILL_ROW_HEIGHT + CARD_GAP + ROOT_PAD_BOTTOM;
const PILL_HEIGHT = CHROME_HEIGHT - CARD_GAP;
const PANEL_INITIAL_HEIGHT = PILL_HEIGHT;
// Keep the panel clear of the menu bar and screen edges when opening at the cursor.
const SCREEN_MARGIN = 16;
const MENU_BAR_CLEARANCE = 40;
// Where the cursor lands inside the window: on the hedgehog, Figma-style.
const CURSOR_IN_WINDOW_X = 55;
const CURSOR_IN_WINDOW_X_OFFSET = 8;
const CURSOR_ABOVE_PILL_PX = 10;
interface QuickAskLayoutState {
  flip: boolean;
  /** Room between the pill's anchor and the screen edge, in CSS pixels. */
  maxHeight: number;
}

/** Last geometry the renderer reported; reused across hides/shows. */
let cachedContentHeight = PANEL_INITIAL_HEIGHT;
/** Whether the current layout has the card above the pill. */
let currentFlip = false;

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
    width: PANEL_WIDTH,
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

  window.setAlwaysOnTop(true, "screen-saver");
  // macOS: a `panel` window already floats over full-screen apps on every
  // Space. Do NOT call setVisibleOnAllWorkspaces with visibleOnFullScreen:
  // it flips the app's activation policy to accessory, which removes the app
  // from the Dock and the Cmd+Tab switcher.
  if (process.platform !== "darwin") {
    window.setVisibleOnAllWorkspaces(true);
  }
  // The window is a large transparent rect around a small pill. Let clicks
  // fall through the empty area; the renderer re-enables interaction while
  // the pointer is over actual content (`forward` keeps sending it the mouse
  // events it needs to detect that).
  window.setIgnoreMouseEvents(true, { forward: true });

  window.on("blur", () => {
    // Keep the panel up while its devtools are focused.
    if (window.webContents.isDevToolsFocused()) return;
    hideQuickAsk();
  });

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

/**
 * Geometry math shared by the summon, resize, and drag paths.
 *
 * `maxHeight` is the room between the pill's anchor and the screen edge in
 * the grow direction. It depends only on position and display — never on the
 * content height the renderer reported. (Deriving the card cap from the
 * window height fed the capped measurement back into the cap, locking the
 * panel at whatever sliver it started at.)
 */
function layoutFor(
  bounds: { x: number; y: number; height: number },
  flip: boolean,
  area: { x: number; y: number; width: number; height: number },
): { y: number; height: number; maxHeight: number } {
  if (!flip) {
    // Window top is anchored at the pill; the card may extend to the screen edge.
    const maxHeight = Math.max(
      PILL_HEIGHT,
      area.y + area.height - SCREEN_MARGIN - bounds.y,
    );
    const height = Math.max(PILL_HEIGHT, Math.min(bounds.height, maxHeight));
    return { y: bounds.y, height, maxHeight };
  }
  // Window bottom is anchored at the pill; the card extends upward, capped
  // by the screen edge above.
  const bottom = bounds.y + bounds.height;
  const maxHeight = Math.max(
    PILL_HEIGHT,
    bottom - (area.y + MENU_BAR_CLEARANCE),
  );
  const height = Math.max(PILL_HEIGHT, Math.min(bounds.height, maxHeight));
  return { y: bottom - height, height, maxHeight };
}

function pushLayout(window: BrowserWindow): void {
  if (window.isDestroyed()) return;
  const bounds = window.getBounds();
  const layout = layoutFor(
    bounds,
    currentFlip,
    screen.getDisplayNearestPoint(bounds).workArea,
  );
  if (layout.y !== bounds.y || layout.height !== bounds.height) {
    window.setBounds({
      x: bounds.x,
      y: layout.y,
      width: PANEL_WIDTH,
      height: layout.height,
    });
  }
  const payload: QuickAskLayoutState = {
    flip: currentFlip,
    maxHeight: layout.maxHeight,
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
 * Position the panel so the cursor lands on the hedgehog's nose (Figma
 * cursor-chat style). Near the bottom of the display the card flips above
 * the pill instead of squeezing into the sliver below.
 */
function positionAtCursor(window: BrowserWindow): void {
  const cursor = screen.getCursorScreenPoint();
  const display = screen.getDisplayNearestPoint(cursor);
  const area = display.workArea;

  const x = Math.round(
    Math.min(
      Math.max(
        cursor.x + CURSOR_IN_WINDOW_X_OFFSET - CURSOR_IN_WINDOW_X,
        area.x + SCREEN_MARGIN,
      ),
      area.x + area.width - PANEL_WIDTH - SCREEN_MARGIN,
    ),
  );
  const pillTopY = cursor.y + CURSOR_ABOVE_PILL_PX;
  const windowTop = pillTopY - ROOT_PAD_TOP;
  const roomBelow =
    area.y + area.height - SCREEN_MARGIN - (windowTop + PILL_HEIGHT);
  const roomAbove =
    pillTopY +
    PILL_ROW_HEIGHT +
    ROOT_PAD_BOTTOM -
    (area.y + MENU_BAR_CLEARANCE);
  // Flip when the card cannot fit below but has at least slightly more room above.
  const needsFlip = roomBelow < cachedContentHeight && roomAbove > roomBelow;
  currentFlip = needsFlip;

  // Flipped: the pill's top edge keeps its anchor, the card extends upward.
  const y = needsFlip
    ? pillTopY - (cachedContentHeight - ROOT_PAD_BOTTOM - PILL_ROW_HEIGHT)
    : windowTop;
  const bounds = {
    x,
    y: Math.round(y),
    width: PANEL_WIDTH,
    height: cachedContentHeight,
  };
  const layout = layoutFor(bounds, needsFlip, area);
  window.setBounds({
    x,
    y: layout.y,
    width: PANEL_WIDTH,
    height: layout.height,
  });
}

function showQuickAsk(): void {
  if (!quickAskWindow || quickAskWindow.isDestroyed()) {
    quickAskWindow = createQuickAskWindow();
  }
  positionAtCursor(quickAskWindow);
  quickAskWindow.setIgnoreMouseEvents(true, { forward: true });
  quickAskWindow.show();
  quickAskWindow.focus();
  quickAskWindow.webContents.send(QUICK_ASK_SHOWN_CHANNEL);
  pushLayout(quickAskWindow);
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
      if (event.type === "viz" && "reason" in event && event.reason) {
        log.warn("Quick ask chart render skipped", { reason: event.reason });
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
  ipcMain.on(QUICK_ASK_RESIZE_CHANNEL, (_event, height: unknown) => {
    if (!quickAskWindow || quickAskWindow.isDestroyed()) return;
    if (typeof height !== "number" || !Number.isFinite(height)) return;
    cachedContentHeight = Math.max(PILL_HEIGHT, Math.round(height));
    pushLayout(quickAskWindow);
  });
  // Dragging: native `-webkit-app-region: drag` is incompatible with the
  // forwarded click-through events, so the renderer reports a grab offset
  // and the main process follows the cursor.
  ipcMain.on(QUICK_ASK_DRAG_START_CHANNEL, (_event, offset: unknown) => {
    if (!quickAskWindow || quickAskWindow.isDestroyed()) return;
    const { dx, dy } = (offset ?? {}) as { dx?: unknown; dy?: unknown };
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
          pushLayout(quickAskWindow);
        }
      }, 15),
    };
  });
  ipcMain.on(QUICK_ASK_DRAG_END_CHANNEL, () => stopDrag());
  ipcMain.on(
    QUICK_ASK_SET_INTERACTIVE_CHANNEL,
    (_event, interactive: unknown) => {
      if (!quickAskWindow || quickAskWindow.isDestroyed()) return;
      if (interactive === true) {
        quickAskWindow.setIgnoreMouseEvents(false);
      } else {
        quickAskWindow.setIgnoreMouseEvents(true, { forward: true });
      }
    },
  );
  ipcMain.on(QUICK_ASK_OPEN_IN_APP_CHANNEL, () => {
    hideQuickAsk();
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
