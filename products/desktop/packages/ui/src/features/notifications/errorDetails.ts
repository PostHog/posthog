import { toast } from "@posthog/ui/primitives/toast";
import { create } from "zustand";

// The error behind an error-level toast, captured so the details dialog can
// show the full payload the toast had no room for.
export interface ErrorDetail {
  title: string;
  error: unknown;
  occurredAt: number;
}

// API error messages routinely arrive as a string with a JSON payload embedded
// in them (e.g. `Failed request: [400] {"detail":"..."}`). Pull that payload
// out and pretty-print it so the details dialog is readable rather than one
// unwrapped line. Returns the string untouched when there's no parseable JSON.
function prettifyErrorString(message: string): string {
  const start = message.indexOf("{");
  const end = message.lastIndexOf("}");
  if (start !== -1 && end > start) {
    const candidate = message.slice(start, end + 1);
    try {
      const parsed: unknown = JSON.parse(candidate);
      const prefix = message.slice(0, start).trim();
      const suffix = message.slice(end + 1).trim();
      const pretty = JSON.stringify(parsed, null, 2);
      return [prefix, pretty, suffix].filter(Boolean).join("\n");
    } catch {
      // Not JSON after all — fall through to the raw string.
    }
  }
  return message;
}

// Pretty-printed JSON of an arbitrary error payload that never throws:
// Error instances become plain objects (keeping message, stack, cause, and
// any enumerable extras like `code`), circular references are elided, and
// non-JSON values fall back to String().
export function serializeError(error: unknown): string {
  // Strings are already human-readable; only reflow an embedded JSON payload.
  if (typeof error === "string") return prettifyErrorString(error);
  const seen = new WeakSet<object>();
  try {
    const json = JSON.stringify(
      error,
      (_key, value: unknown) => {
        if (typeof value === "object" && value !== null) {
          if (seen.has(value)) return "[circular]";
          seen.add(value);
        }
        if (value instanceof Error) {
          return {
            name: value.name,
            message: value.message,
            stack: value.stack,
            cause: value.cause,
            ...Object.fromEntries(Object.entries(value)),
          };
        }
        if (typeof value === "bigint" || typeof value === "function") {
          return String(value);
        }
        return value;
      },
      2,
    );
    return json ?? String(error);
  } catch {
    return String(error);
  }
}

const SUMMARY_LIMIT = 140;

// One-line summary of an error payload, sized for a toast description. The
// full payload stays behind the toast's "Details" action.
export function summarizeError(error: unknown): string {
  let message: string;
  if (typeof error === "string") {
    message = error;
  } else if (error instanceof Error) {
    message = error.message;
  } else if (
    typeof error === "object" &&
    error !== null &&
    "message" in error &&
    typeof (error as { message: unknown }).message === "string"
  ) {
    message = (error as { message: string }).message;
  } else {
    message = serializeError(error);
  }
  const flat = message.replace(/\s+/g, " ").trim();
  if (flat.length === 0) return "Unknown error";
  return flat.length <= SUMMARY_LIMIT
    ? flat
    : `${flat.slice(0, SUMMARY_LIMIT)}…`;
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

// Open the error details dialog for a given error. Shared by the notification
// bus's error toasts and the standalone `toastError` helper so both land on the
// same inspectable dialog.
export function showErrorDetails(title: string, error: unknown): void {
  useErrorDetailsStore.getState().show({
    title,
    error,
    occurredAt: Date.now(),
  });
}

// Fire an error toast whose payload stays inspectable: a one-line summary in
// the toast body plus a "Details" action that opens the full pretty-printed
// error (and its logs) in the dialog. Use this instead of a bare
// `toast.error(title, { description: someRawError })` — that overflows the
// toast and can't be opened. This is the lightweight, synchronous path for
// errors raised by a user action; task-lifecycle notifications that need
// focus-aware routing and sound still go through `NotificationBus.notifyError`.
export function toastError(
  title: string,
  error: unknown,
  options?: { id?: string; duration?: number },
): void {
  toast.error(title, {
    id: options?.id,
    duration: options?.duration,
    description: summarizeError(error),
    action: {
      label: "Details",
      onClick: () => showErrorDetails(title, error),
    },
  });
}
