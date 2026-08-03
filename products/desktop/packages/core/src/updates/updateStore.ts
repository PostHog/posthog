import type { UpdatesStatusPayload } from "@posthog/core/updates/schemas";
import { createStore } from "zustand/vanilla";

export type UpdateUiStatus =
  | "idle"
  | "available"
  | "checking"
  | "downloading"
  | "ready"
  | "installing";

interface UpdateState {
  status: UpdateUiStatus;
  version: string | null;
  availableVersion: string | null;
  releaseNotes: string | null;
  releaseDate: string | null;
  downloadPercent: number | null;
  bytesPerSecond: number | null;
  downloadSizeBytes: number | null;
  isEnabled: boolean;
  menuCheckPending: boolean;

  setStatus: (status: UpdateUiStatus) => void;
  setVersion: (version: string | null) => void;
  setEnabled: (isEnabled: boolean) => void;
  setMenuCheckPending: (menuCheckPending: boolean) => void;
  setReady: (version: string | null) => void;
  applyStatusUpdate: (update: UpdateStatusUpdate) => void;
}

export const updateStore = createStore<UpdateState>((set) => ({
  status: "idle",
  version: null,
  availableVersion: null,
  releaseNotes: null,
  releaseDate: null,
  downloadPercent: null,
  bytesPerSecond: null,
  downloadSizeBytes: null,
  isEnabled: false,
  menuCheckPending: false,

  setStatus: (status) => set({ status }),
  setVersion: (version) => set({ version }),
  setEnabled: (isEnabled) => set({ isEnabled }),
  setMenuCheckPending: (menuCheckPending) => set({ menuCheckPending }),
  setReady: (version) => set({ status: "ready", version }),
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
