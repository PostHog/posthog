import Store from "electron-store";
import { getUserDataDir } from "./env";
import { logger } from "./logger";

const log = logger.scope("store");

/** Structurally matches Electron's Rectangle (not imported here — utils stay electron-free). */
export interface DisplayBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface FocusSession {
  mainRepoPath: string;
  worktreePath: string;
  branch: string;
  originalBranch: string;
  mainStashRef: string | null;
  commitSha: string;
}

interface FocusStoreSchema {
  sessions: Record<string, FocusSession>;
}

interface RendererStoreSchema {
  [key: string]: string;
}

interface QuickAskStoreSchema {
  panelEnabled: boolean;
  shortcut: string;
  defaultChannelId: string;
  defaultRepositories: string[];
  defaultGithubIntegrationId: number;
  defaultAdapter: string;
  defaultModel: string;
  defaultEffort: string;
}

export interface WindowStateSchema {
  x: number | undefined;
  y: number | undefined;
  width: number;
  height: number;
  isMaximized: boolean;
  zoomLevel: number;
  isFullScreen: boolean;
  fullScreenDisplayBounds: DisplayBounds | undefined;
  restoreFullScreenOnNextLaunch: boolean;
}

/** Window state, plus the one-shot flags the next window load reads. */
interface MainWindowStoreSchema extends WindowStateSchema {
  quarantinedRoute: string | undefined;
}

const userDataDir = getUserDataDir();

export const rendererStore = new Store<RendererStoreSchema>({
  name: "renderer-storage",
  cwd: userDataDir,
});

export const focusStore = new Store<FocusStoreSchema>({
  name: "focus",
  cwd: userDataDir,
  defaults: { sessions: {} },
});

export const quickAskStore = new Store<QuickAskStoreSchema>({
  name: "quick-ask",
  cwd: userDataDir,
  defaults: {
    panelEnabled: false,
    shortcut: "",
    defaultChannelId: "",
    defaultRepositories: [],
    defaultGithubIntegrationId: 0,
    defaultAdapter: "",
    defaultModel: "",
    defaultEffort: "",
  },
});

export const windowStateStore = new Store<MainWindowStoreSchema>({
  name: "window-state",
  cwd: userDataDir,
  defaults: {
    x: undefined,
    y: undefined,
    width: 1200,
    height: 600,
    isMaximized: true,
    zoomLevel: 0,
    isFullScreen: false,
    fullScreenDisplayBounds: undefined,
    restoreFullScreenOnNextLaunch: false,
    quarantinedRoute: undefined,
  },
});

/**
 * Persist a single window-state key. electron-store writes synchronously and
 * throws on failure (e.g. ENOSPC on a full disk). Window-state persistence is
 * non-critical, so swallow and log the error instead of letting it propagate
 * into an event/timer callback and crash the main process.
 */
function setWindowState<K extends keyof MainWindowStoreSchema>(
  key: K,
  value: MainWindowStoreSchema[K],
): void {
  try {
    windowStateStore.set(key, value);
  } catch (error) {
    log.warn(`Failed to persist window state "${key}"`, { error });
  }
}

export function saveZoomLevel(level: number): void {
  setWindowState("zoomLevel", level);
}

export function saveFullScreenState(isFullScreen: boolean): void {
  setWindowState("isFullScreen", isFullScreen);
}

export function getFullScreenState(): boolean {
  return windowStateStore.get("isFullScreen", false);
}

/**
 * The bounds of the display the window was last fullscreened on, so the
 * post-update relaunch can restore fullscreen on the same monitor.
 */
export function saveFullScreenDisplayBounds(bounds: DisplayBounds): void {
  windowStateStore.set("fullScreenDisplayBounds", bounds);
}

export function getFullScreenDisplayBounds(): DisplayBounds | undefined {
  return windowStateStore.get("fullScreenDisplayBounds", undefined);
}

/**
 * Set only when the app quits to install an update, so a fullscreen session
 * is restored after the "restart to apply" handoff.
 * A normal quit leaves it false and launches windowed.
 */
export function setRestoreFullScreenOnNextLaunch(restore: boolean): void {
  setWindowState("restoreFullScreenOnNextLaunch", restore);
}

/**
 * The in-app route the renderer crashed on repeatedly. It survives a restart
 * because the app restores the last route it was on, so an unpersisted marker
 * would send the next launch straight back into the crash.
 */
export function setQuarantinedRoute(route: string): void {
  setWindowState("quarantinedRoute", route);
}

/** Reads the quarantined route and clears it, so it applies to one load only. */
export function takeQuarantinedRoute(): string | undefined {
  const route = windowStateStore.get("quarantinedRoute", undefined);
  if (route) setWindowState("quarantinedRoute", undefined);
  return route;
}
