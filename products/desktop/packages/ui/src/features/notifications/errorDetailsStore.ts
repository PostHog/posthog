import { create } from "zustand";

// The error behind an error-level toast, captured so the details dialog can
// show the full payload the toast had no room for.
export interface ErrorDetail {
  title: string;
  error: unknown;
  occurredAt: number;
}

interface ErrorDetailsState {
  detail: ErrorDetail | null;
  show: (detail: ErrorDetail) => void;
  close: () => void;
}

// View state for the global error details dialog (rendered once in App).
export const useErrorDetailsStore = create<ErrorDetailsState>((set) => ({
  detail: null,
  show: (detail) => set({ detail }),
  close: () => set({ detail: null }),
}));

// Open the error details dialog for a given error. The central toast wrapper
// uses this for every error toast so even plain strings remain inspectable.
export function showErrorDetails(title: string, error: unknown): void {
  useErrorDetailsStore.getState().show({
    title,
    error,
    occurredAt: Date.now(),
  });
}
