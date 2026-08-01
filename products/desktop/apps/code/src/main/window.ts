import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createIPCHandler } from "@posthog/electron-trpc/main";
import { MAIN_WINDOW_SERVICE } from "@posthog/platform/main-window";
import { DARK_APP_BACKGROUND_COLOR } from "@posthog/shared/constants";
import {
  app,
  BrowserWindow,
  Menu,
  type MenuItemConstructorOptions,
  screen,
} from "electron";
import { container } from "./di/container";
import { setupExternalLinkHandlers } from "./external-links";
import { buildApplicationMenu } from "./menu";
import type { ElectronMainWindow } from "./platform-adapters/electron-main-window";
import { posthogNodeAnalytics } from "./platform-adapters/posthog-analytics";
import { POSTHOG_SESSION_ID_ARG } from "./posthog-session-arg";
import {
  encodeDevFlagsForArg,
  readDevFlagsSync,
} from "./services/dev-flags/service";
import { trpcRouter } from "./trpc/router";
import { collectMemorySnapshot } from "./utils/crash-diagnostics";
import { isDevBuild } from "./utils/env";
import { logger, readChromiumLogTail } from "./utils/logger";
import {
  getFullScreenDisplayBounds,
  saveFullScreenDisplayBounds,
  saveFullScreenState,
  setRestoreFullScreenOnNextLaunch,
  type WindowStateSchema,
  windowStateStore,
} from "./utils/store";
import { setupWindowZoom } from "./zoom";

const log = logger.scope("window");
const trpcLog = logger.scope("host-trpc");

const MAIN_WINDOW_VITE_DEV_SERVER_URL = process.env.ELECTRON_RENDERER_URL;
const MAIN_WINDOW_VITE_NAME = "main_window";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function isPositionOnScreen(x: number, y: number): boolean {
  const displays = screen.getAllDisplays();
  return displays.some((display) => {
    const { x: dx, y: dy, width, height } = display.bounds;
    return x >= dx && x < dx + width && y >= dy && y < dy + height;
  });
}

function getSavedWindowState(): WindowStateSchema {
  const state = {
    x: windowStateStore.get("x"),
    y: windowStateStore.get("y"),
    width: windowStateStore.get("width", 1200),
    height: windowStateStore.get("height", 600),
    isMaximized: windowStateStore.get("isMaximized", true),
    zoomLevel: windowStateStore.get("zoomLevel", 0),
    isFullScreen: windowStateStore.get("isFullScreen", false),
    fullScreenDisplayBounds: windowStateStore.get(
      "fullScreenDisplayBounds",
      undefined,
    ),
    restoreFullScreenOnNextLaunch: windowStateStore.get(
      "restoreFullScreenOnNextLaunch",
      false,
    ),
  };

  // Validate position is still on a connected display
  if (state.x !== undefined && state.y !== undefined) {
    if (!isPositionOnScreen(state.x, state.y)) {
      state.x = undefined;
      state.y = undefined;
    }
  }

  return state;
}

export function saveWindowState(window: BrowserWindow): void {
  // electron-store writes synchronously and throws on failure (e.g. ENOSPC on a
  // full disk). This runs inside window-event and setTimeout callbacks, where an
  // uncaught throw would crash the main process. Window-state persistence is
  // non-critical, so swallow and log the error instead.
  try {
    const isMaximized = window.isMaximized();
    windowStateStore.set("isMaximized", isMaximized);

    // Only save bounds when not maximized, so restoring from maximized
    // gives the user their previous windowed size/position
    if (!isMaximized && !window.isFullScreen()) {
      const bounds = window.getBounds();
      windowStateStore.set("x", bounds.x);
      windowStateStore.set("y", bounds.y);
      windowStateStore.set("width", bounds.width);
      windowStateStore.set("height", bounds.height);
    }
  } catch (error) {
    log.warn("Failed to persist window state", { error });
  }
}

let mainWindow: BrowserWindow | null = null;

export function focusMainWindow(reason: string): void {
  if (mainWindow) {
    log.info("focusMainWindow called", {
      reason,
      isMinimized: mainWindow.isMinimized(),
      isFocused: mainWindow.isFocused(),
      isVisible: mainWindow.isVisible(),
      stack: new Error().stack,
    });
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
}

function setupCrashLogging(window: BrowserWindow): void {
  window.webContents.on("render-process-gone", (_event, details) => {
    log.error("Renderer process gone", {
      reason: details.reason,
      exitCode: details.exitCode,
      url: window.webContents.getURL(),
      memory: collectMemorySnapshot(() => app.getAppMetrics()),
      chromiumLogTail: readChromiumLogTail(),
    });
  });

  window.on("unresponsive", () => {
    log.warn("Window unresponsive", {
      url: window.webContents.getURL(),
      memory: collectMemorySnapshot(() => app.getAppMetrics()),
      chromiumLogTail: readChromiumLogTail(),
    });
  });

  window.on("responsive", () => {
    log.info("Window responsive again");
  });
}

function setupEditableContextMenu(window: BrowserWindow): void {
  window.webContents.on("context-menu", (_event, params) => {
    if (!params.isEditable) return;
    const { editFlags } = params;
    const template: MenuItemConstructorOptions[] = [
      { role: "undo", enabled: editFlags.canUndo },
      { role: "redo", enabled: editFlags.canRedo },
      { type: "separator" },
      { role: "cut", enabled: editFlags.canCut },
      { role: "copy", enabled: editFlags.canCopy },
      { role: "paste", enabled: editFlags.canPaste },
      { type: "separator" },
      { role: "selectAll", enabled: editFlags.canSelectAll },
    ];
    Menu.buildFromTemplate(template).popup({ window });
  });
}

export function createWindow(): void {
  const isDev = isDevBuild();
  const savedState = getSavedWindowState();

  // Read the one-shot fullscreen-restore flag and clear it immediately, so it
  // only ever affects the single launch that follows an update restart.
  const restoreFullScreen = savedState.restoreFullScreenOnNextLaunch;
  if (restoreFullScreen) {
    setRestoreFullScreenOnNextLaunch(false);

    // setFullScreen(true) fullscreens whichever display the window is on, so
    // start the hidden window on the display that was fullscreen before the
    // update. getDisplayMatching falls back to the nearest display if that
    // monitor is gone.
    const displayBounds = getFullScreenDisplayBounds();
    if (displayBounds) {
      const { workArea } = screen.getDisplayMatching(displayBounds);
      savedState.width = Math.min(savedState.width, workArea.width);
      savedState.height = Math.min(savedState.height, workArea.height);
      savedState.x = Math.round(
        workArea.x + (workArea.width - savedState.width) / 2,
      );
      savedState.y = Math.round(
        workArea.y + (workArea.height - savedState.height) / 2,
      );
    }
  }

  let saveTimeout: ReturnType<typeof setTimeout> | null = null;

  const scheduleSaveWindowState = (window: BrowserWindow): void => {
    if (saveTimeout) {
      clearTimeout(saveTimeout);
    }

    saveTimeout = setTimeout(() => {
      if (!window.isDestroyed()) {
        saveWindowState(window);
      }
      saveTimeout = null;
    }, 200);
  };

  const platformWindowConfig =
    process.platform === "darwin"
      ? {
          titleBarStyle: "hiddenInset" as const,
          // Centre the traffic lights vertically with the title bar's back/forward
          // buttons (40px bar, 24px buttons → centre at y=20; 12px dots → top at 14).
          // x mirrors y so the inset from the top and the left match.
          trafficLightPosition: { x: 14, y: 14 },
          // Exposes the titlebar-area-* CSS env vars so the renderer can
          // clear the traffic lights exactly; their size varies by macOS
          // version (bigger on Tahoe), so it must not hardcode a width.
          titleBarOverlay: true,
        }
      : process.platform === "win32"
        ? {
            titleBarStyle: "hidden" as const,
            titleBarOverlay: {
              color: DARK_APP_BACKGROUND_COLOR,
              symbolColor: "#ffffff",
              height: 36,
            },
          }
        : {};

  // macOS uses the .app bundle icon, but Linux/Windows need an explicit icon
  const windowIcon =
    process.platform !== "darwin"
      ? app.isPackaged
        ? path.join(process.resourcesPath, "app-icon.png")
        : path.join(app.getAppPath(), "build/app-icon.png")
      : undefined;

  mainWindow = new BrowserWindow({
    ...(savedState.x !== undefined && { x: savedState.x }),
    ...(savedState.y !== undefined && { y: savedState.y }),
    width: savedState.width,
    height: savedState.height,
    minWidth: 800,
    minHeight: 600,
    backgroundColor: DARK_APP_BACKGROUND_COLOR,
    ...(windowIcon ? { icon: windowIcon } : {}),
    ...platformWindowConfig,
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, "preload.js"),
      enableBlinkFeatures: "GetDisplayMedia",
      partition: "persist:main",
      additionalArguments: [
        ...(isDev ? ["--posthog-code-dev"] : []),
        `${POSTHOG_SESSION_ID_ARG}${posthogNodeAnalytics.getOrCreateSessionId()}`,
        encodeDevFlagsForArg(readDevFlagsSync()),
      ],
      ...(isDev && { webSecurity: false }),
    },
  });

  let windowShown = false;
  const showWindow = () => {
    if (windowShown) return;
    windowShown = true;
    clearTimeout(showFallback);
    if (restoreFullScreen) {
      mainWindow?.setFullScreen(true);
    } else if (savedState.isMaximized) {
      mainWindow?.maximize();
    }
    mainWindow?.show();
    mainWindow?.moveTop();
    mainWindow?.focus();
    app.focus({ steal: true });
  };

  mainWindow.once("ready-to-show", showWindow);
  const showFallback = setTimeout(showWindow, 3000);

  setupWindowZoom(mainWindow);

  // Persist window state on changes
  mainWindow.on(
    "resize",
    () => mainWindow && scheduleSaveWindowState(mainWindow),
  );
  mainWindow.on(
    "move",
    () => mainWindow && scheduleSaveWindowState(mainWindow),
  );
  mainWindow.on("maximize", () => mainWindow && saveWindowState(mainWindow));
  mainWindow.on("unmaximize", () => mainWindow && saveWindowState(mainWindow));
  mainWindow.on("close", () => mainWindow && saveWindowState(mainWindow));

  // Live-track fullscreen (and which display it is on) so the update-quit
  // path can restore the same monitor after the relaunch.
  mainWindow.on("enter-full-screen", () => {
    saveFullScreenState(true);
    if (mainWindow) {
      saveFullScreenDisplayBounds(
        screen.getDisplayMatching(mainWindow.getBounds()).bounds,
      );
    }
  });
  mainWindow.on("leave-full-screen", () => saveFullScreenState(false));

  container
    .get<ElectronMainWindow>(MAIN_WINDOW_SERVICE)
    .setMainWindowGetter(() => mainWindow);

  createIPCHandler({
    router: trpcRouter,
    windows: [mainWindow],
    createContext: async () => ({ container }),
    // Input is deliberately not logged — it can carry tokens or file contents.
    onError: ({ error, path, type }) => {
      trpcLog.error(`${type} '${path ?? "<unknown>"}' failed (${error.code})`, {
        message: error.message,
        cause: error.cause instanceof Error ? error.cause.stack : error.cause,
      });
    },
  });

  const rendererFilePath = path.join(
    __dirname,
    `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`,
  );
  // The URL the renderer is served from, used to tell in-app navigations from
  // external links. In dev it's the Vite server origin; in prod it's the
  // packaged index.html file URL.
  const appHome = MAIN_WINDOW_VITE_DEV_SERVER_URL
    ? new URL(MAIN_WINDOW_VITE_DEV_SERVER_URL)
    : pathToFileURL(rendererFilePath);

  setupExternalLinkHandlers(mainWindow, appHome);
  setupEditableContextMenu(mainWindow);
  setupCrashLogging(mainWindow);
  buildApplicationMenu();

  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);
  } else {
    mainWindow.loadFile(rendererFilePath);
  }

  mainWindow.on("closed", () => {
    if (saveTimeout) {
      clearTimeout(saveTimeout);
      saveTimeout = null;
    }
    mainWindow = null;
  });
}
