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
  QUICK_ASK_EVENT_CHANNEL,
  QUICK_ASK_HIDE_CHANNEL,
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
const PANEL_INITIAL_HEIGHT = 96;
const PANEL_MAX_HEIGHT = 620;
// Keep the panel clear of the menu bar and screen edges when opening at the cursor.
const SCREEN_MARGIN = 16;
const MENU_BAR_CLEARANCE = 40;

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
  window.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
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

/** Position the panel at the cursor, clamped to the cursor's display. */
function positionAtCursor(window: BrowserWindow): void {
  const cursor = screen.getCursorScreenPoint();
  const display = screen.getDisplayNearestPoint(cursor);
  const { x: dx, y: dy, width: dw, height: dh } = display.workArea;

  const x = Math.round(
    Math.min(
      Math.max(cursor.x - 24, dx + SCREEN_MARGIN),
      dx + dw - PANEL_WIDTH - SCREEN_MARGIN,
    ),
  );
  const y = Math.round(
    Math.min(
      Math.max(cursor.y - 24, dy + MENU_BAR_CLEARANCE),
      dy + dh - PANEL_MAX_HEIGHT - SCREEN_MARGIN,
    ),
  );

  window.setBounds({ x, y, width: PANEL_WIDTH, height: PANEL_INITIAL_HEIGHT });
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
}

function hideQuickAsk(): void {
  getQuickAskService().cancel();
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
    const clamped = Math.round(
      Math.min(Math.max(height, PANEL_INITIAL_HEIGHT), PANEL_MAX_HEIGHT),
    );
    const bounds = quickAskWindow.getBounds();
    quickAskWindow.setBounds({ ...bounds, height: clamped });
  });
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
