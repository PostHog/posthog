import type { UpdatesStatusPayload } from "@posthog/core/updates/schemas";
import { createStore } from "zustand/vanilla";

export type UpdateUiStatus =
  | "idle"
  | "available"
  | "checking"
  | "downloading"
  | "ready"
  | "installing";

/**
 * Deferred install ("restart when idle") lifecycle: `off` until the user arms
 * it, `waiting` while local agents are still working, `countdown` once the app
 * is idle and a cancellable restart timer is running.
 */
export type DeferredInstallPhase = "off" | "waiting" | "countdown";

export const DEFERRED_INSTALL_COUNTDOWN_SECONDS = 10;

interface UpdateState {
  status: UpdateUiStatus;
  version: string | null;
  availableVersion: string | null;
  currentVersion: string | null;
  releaseNotes: string | null;
  releaseDate: string | null;
  downloadPercent: number | null;
  bytesPerSecond: number | null;
  downloadSizeBytes: number | null;
  isEnabled: boolean;
  menuCheckPending: boolean;
  deferredInstallPhase: DeferredInstallPhase;
  deferredInstallCountdown: number | null;

  setStatus: (status: UpdateUiStatus) => void;
  setVersion: (version: string | null) => void;
  setCurrentVersion: (currentVersion: string | null) => void;
  setEnabled: (isEnabled: boolean) => void;
  setMenuCheckPending: (menuCheckPending: boolean) => void;
  setReady: (version: string | null) => void;
  armDeferredInstall: () => void;
  disarmDeferredInstall: () => void;
  beginDeferredInstallCountdown: (seconds: number) => void;
  tickDeferredInstallCountdown: (seconds: number) => void;
  returnDeferredInstallToWaiting: () => void;
  applyStatusUpdate: (update: UpdateStatusUpdate) => void;
}

export const updateStore = createStore<UpdateState>((set) => ({
  status: "idle",
  version: null,
  availableVersion: null,
  currentVersion: null,
  releaseNotes: null,
  releaseDate: null,
  downloadPercent: null,
  bytesPerSecond: null,
  downloadSizeBytes: null,
  isEnabled: false,
  menuCheckPending: false,
  deferredInstallPhase: "off",
  deferredInstallCountdown: null,

  setStatus: (status) => set({ status }),
  setVersion: (version) => set({ version }),
  setCurrentVersion: (currentVersion) => set({ currentVersion }),
  setEnabled: (isEnabled) => set({ isEnabled }),
  setMenuCheckPending: (menuCheckPending) => set({ menuCheckPending }),
  setReady: (version) => set({ status: "ready", version }),
  armDeferredInstall: () =>
    set({ deferredInstallPhase: "waiting", deferredInstallCountdown: null }),
  disarmDeferredInstall: () =>
    set({ deferredInstallPhase: "off", deferredInstallCountdown: null }),
  beginDeferredInstallCountdown: (seconds) =>
    set({
      deferredInstallPhase: "countdown",
      deferredInstallCountdown: seconds,
    }),
  tickDeferredInstallCountdown: (seconds) =>
    set({ deferredInstallCountdown: seconds }),
  returnDeferredInstallToWaiting: () =>
    set({ deferredInstallPhase: "waiting", deferredInstallCountdown: null }),
  applyStatusUpdate: (update) =>
    set((state) => ({
      status: update.status ?? state.status,
      version: update.version !== undefined ? update.version : state.version,
      availableVersion:
        update.availableVersion !== undefined
          ? update.availableVersion
          : state.availableVersion,
      releaseNotes:
        update.releaseNotes !== undefined
          ? update.releaseNotes
          : state.releaseNotes,
      releaseDate:
        update.releaseDate !== undefined
          ? update.releaseDate
          : state.releaseDate,
      downloadPercent:
        update.downloadPercent !== undefined
          ? update.downloadPercent
          : state.downloadPercent,
      bytesPerSecond:
        update.bytesPerSecond !== undefined
          ? update.bytesPerSecond
          : state.bytesPerSecond,
      downloadSizeBytes:
        update.downloadSizeBytes !== undefined
          ? update.downloadSizeBytes
          : state.downloadSizeBytes,
    })),
}));

export const getUpdateUiStatus = () => updateStore.getState().status;
export const getUpdateVersion = () => updateStore.getState().version;
export const getMenuCheckPending = () =>
  updateStore.getState().menuCheckPending;

export interface UpdateStatusUpdate {
  status?: UpdateUiStatus;
  version?: string | null;
  availableVersion?: string | null;
  releaseNotes?: string | null;
  releaseDate?: string | null;
  downloadPercent?: number | null;
  bytesPerSecond?: number | null;
  downloadSizeBytes?: number | null;
}

export function deriveUpdateUiStatus(
  payload: UpdatesStatusPayload,
  currentStatus: UpdateUiStatus,
): UpdateStatusUpdate | null {
  if (payload.installing) {
    return { status: "installing", version: payload.version ?? null };
  }

  if (payload.updateReady) {
    return { status: "ready", version: payload.version ?? null };
  }

  if (payload.checking && payload.downloading) {
    return {
      status: "downloading",
      version: null,
      availableVersion: payload.availableVersion ?? null,
      releaseNotes: payload.releaseNotes ?? null,
      releaseDate: payload.releaseDate ?? null,
      downloadPercent: payload.downloadPercent ?? null,
      bytesPerSecond: payload.bytesPerSecond ?? null,
      downloadSizeBytes: payload.downloadSizeBytes ?? null,
    };
  }

  if (payload.available) {
    return {
      status: "available",
      version: null,
      availableVersion: payload.availableVersion ?? null,
      releaseNotes: payload.releaseNotes ?? null,
      releaseDate: payload.releaseDate ?? null,
      downloadSizeBytes: payload.downloadSizeBytes ?? null,
    };
  }

  if (payload.checking) {
    return { status: "checking" };
  }

  if (payload.upToDate || payload.error) {
    if (currentStatus !== "ready" && currentStatus !== "installing") {
      return { status: "idle" };
    }
  }

  return null;
}

export interface MenuCheckToast {
  kind: "success" | "error";
  message: string;
  description?: string;
}

export interface MenuCheckOutcome {
  toast?: MenuCheckToast;
  clearPending: boolean;
}

export function resolveMenuCheckFromStatus(
  payload: UpdatesStatusPayload,
  menuCheckPending: boolean,
): MenuCheckOutcome | null {
  if (!menuCheckPending) {
    return null;
  }

  if (payload.upToDate) {
    return {
      clearPending: true,
      toast: { kind: "success", message: "You're on the latest version" },
    };
  }

  if (payload.error) {
    return {
      clearPending: true,
      toast: {
        kind: "error",
        message: "Failed to check for updates",
        description: payload.error,
      },
    };
  }

  if (payload.checking === false) {
    return { clearPending: true };
  }

  return null;
}

export interface MenuCheckResult {
  success: boolean;
  errorCode?: string;
  errorMessage?: string;
}

export type DeferredInstallTransition =
  | "begin-countdown"
  | "return-to-waiting"
  | "disarm";

/**
 * Decides how an armed "restart when idle" install reacts to update-status and
 * agent-activity changes. Cloud runs continue server-side across a restart, so
 * `busyLocalSessions` counts only local agents mid-turn. The arm survives a
 * newer update arriving (ready → downloading → ready); it is only dropped when
 * an install is already underway or updates shut off entirely.
 */
export function deriveDeferredInstallTransition(input: {
  phase: DeferredInstallPhase;
  updateStatus: UpdateUiStatus;
  busyLocalSessions: number;
}): DeferredInstallTransition | null {
  const { phase, updateStatus, busyLocalSessions } = input;
  if (phase === "off") {
    return null;
  }
  if (updateStatus === "installing" || updateStatus === "idle") {
    return "disarm";
  }
  if (phase === "waiting") {
    return updateStatus === "ready" && busyLocalSessions === 0
      ? "begin-countdown"
      : null;
  }
  return updateStatus !== "ready" || busyLocalSessions > 0
    ? "return-to-waiting"
    : null;
}

export function resolveMenuCheckResult(
  result: MenuCheckResult,
): MenuCheckOutcome | null {
  if (result.success) {
    return null;
  }

  if (result.errorCode === "disabled") {
    return {
      clearPending: true,
      toast: {
        kind: "error",
        message: result.errorMessage ?? "Updates not available",
      },
    };
  }

  if (result.errorCode === "already_checking") {
    return null;
  }

  return { clearPending: true };
}
