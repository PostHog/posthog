import { saveZoomLevel, windowStateStore } from "./utils/store";

export const ZOOM_STEP = 0.5;

const ZOOM_MIN = -3;
const ZOOM_MAX = 3;

interface ZoomWebContents {
  getZoomLevel(): number;
  isDestroyed(): boolean;
  on(event: "did-finish-load", listener: () => void): void;
  on(
    event: "zoom-changed",
    listener: (
      event: { preventDefault(): void },
      zoomDirection: "in" | "out",
    ) => void,
  ): void;
  setZoomLevel(level: number): void;
}

interface ZoomWindow {
  on(
    event:
      | "enter-full-screen"
      | "leave-full-screen"
      | "maximize"
      | "resize"
      | "resized"
      | "unmaximize",
    listener: () => void,
  ): void;
  webContents: ZoomWebContents;
}

interface ZoomState {
  currentZoomLevel: number;
  deferredActions: Array<() => void>;
  wheelZoomDelta: number;
  wheelZoomTimeout: ReturnType<typeof setTimeout> | null;
}

const zoomStates = new WeakMap<ZoomWindow, ZoomState>();

function clampZoomLevel(level: number): number {
  return Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, level));
}

function getSavedZoomLevel(): number {
  return clampZoomLevel(windowStateStore.get("zoomLevel", 0));
}

function getCurrentZoomLevel(window: ZoomWindow): number {
  return zoomStates.get(window)?.currentZoomLevel ?? getSavedZoomLevel();
}

function runAfterWheelZoom(window: ZoomWindow, action: () => void): void {
  const state = zoomStates.get(window);
  if (!state?.wheelZoomTimeout) {
    action();
    return;
  }

  state.deferredActions.push(action);
}

export function setWindowZoom(window: ZoomWindow, level: number): void {
  if (window.webContents.isDestroyed()) return;
  const nextLevel = clampZoomLevel(level);
  const state = zoomStates.get(window);
  if (state) state.currentZoomLevel = nextLevel;
  window.webContents.setZoomLevel(nextLevel);
  saveZoomLevel(nextLevel);
}

export function adjustWindowZoom(
  window: ZoomWindow,
  delta: number | "reset",
): void {
  runAfterWheelZoom(window, () => {
    const nextLevel =
      delta === "reset" ? 0 : getCurrentZoomLevel(window) + delta;
    setWindowZoom(window, nextLevel);
  });
}

export function restoreWindowZoom(window: ZoomWindow): void {
  runAfterWheelZoom(window, () => {
    if (window.webContents.isDestroyed()) return;
    const zoomLevel = getCurrentZoomLevel(window);
    if (window.webContents.getZoomLevel() !== zoomLevel) {
      window.webContents.setZoomLevel(zoomLevel);
    }
  });
}

export function setupWindowZoom(window: ZoomWindow): void {
  const state: ZoomState = {
    currentZoomLevel: getSavedZoomLevel(),
    deferredActions: [],
    wheelZoomDelta: 0,
    wheelZoomTimeout: null,
  };
  let restoreTimeout: ReturnType<typeof setTimeout> | null = null;
  zoomStates.set(window, state);

  const scheduleRestore = () => {
    if (restoreTimeout) clearTimeout(restoreTimeout);
    restoreTimeout = setTimeout(() => {
      restoreTimeout = null;
      restoreWindowZoom(window);
    }, 0);
  };

  window.webContents.on("did-finish-load", () => restoreWindowZoom(window));
  window.webContents.on("zoom-changed", (event, zoomDirection) => {
    event.preventDefault();
    state.wheelZoomDelta += zoomDirection === "in" ? ZOOM_STEP : -ZOOM_STEP;
    state.wheelZoomTimeout ??= setTimeout(() => {
      const nextLevel = state.currentZoomLevel + state.wheelZoomDelta;
      state.wheelZoomDelta = 0;
      state.wheelZoomTimeout = null;
      setWindowZoom(window, nextLevel);
      const deferredActions = state.deferredActions.splice(0);
      for (const action of deferredActions) action();
    }, 0);
  });

  window.on("maximize", scheduleRestore);
  window.on("unmaximize", scheduleRestore);
  window.on("resize", scheduleRestore);
  window.on("resized", scheduleRestore);
  window.on("enter-full-screen", scheduleRestore);
  window.on("leave-full-screen", scheduleRestore);
}
