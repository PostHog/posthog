import { create } from "zustand";
import type { SessionNotificationAttachment } from "../types";

/**
 * Optimistic chat-thread echo for a prompt the user just submitted but whose
 * canonical SSE copy hasn't landed yet. Keyed first by a transient UUID (set
 * the instant the user taps send, before any task ID is known) and then
 * `move`d onto the real task ID once `createTask` returns.
 *
 * Pure UI state — not persisted. Cleared as soon as the live session echoes
 * the matching `user_message_chunk` back.
 */
export interface PendingTaskPrompt {
  promptText: string;
  attachments?: SessionNotificationAttachment[];
  // Submit-time epoch ms. Consumers compare event `ts` against this so the
  // echo is only deduped against `user_message_chunk`s that arrived *after*
  // submit — protects against text-identical historical turns (e.g. a user
  // submitting "Continue" twice in a row) hiding the new optimistic echo.
  setAt: number;
}

interface PendingTaskPromptState {
  byKey: Record<string, PendingTaskPrompt>;
  set: (key: string, prompt: PendingTaskPrompt) => void;
  move: (fromKey: string, toKey: string) => void;
  clear: (key: string) => void;
}

export const usePendingTaskPromptStore = create<PendingTaskPromptState>(
  (set) => ({
    byKey: {},
    set: (key, prompt) =>
      set((state) => ({ byKey: { ...state.byKey, [key]: prompt } })),
    move: (fromKey, toKey) =>
      set((state) => {
        const value = state.byKey[fromKey];
        if (!value) return state;
        const { [fromKey]: _removed, ...rest } = state.byKey;
        return { byKey: { ...rest, [toKey]: value } };
      }),
    clear: (key) =>
      set((state) => {
        if (!(key in state.byKey)) return state;
        const { [key]: _removed, ...rest } = state.byKey;
        return { byKey: rest };
      }),
  }),
);

export function usePendingTaskPrompt(
  key: string | undefined | null,
): PendingTaskPrompt | undefined {
  return usePendingTaskPromptStore((s) => (key ? s.byKey[key] : undefined));
}

/**
 * Non-reactive accessors so non-component code (screens, async flows) can
 * mutate the store without going through hooks. Mirrors the desktop
 * `pendingTaskPromptStoreApi` shape.
 */
export const pendingTaskPromptStoreApi = {
  set(key: string, prompt: PendingTaskPrompt): void {
    usePendingTaskPromptStore.getState().set(key, prompt);
  },
  get(key: string): PendingTaskPrompt | undefined {
    return usePendingTaskPromptStore.getState().byKey[key];
  },
  move(fromKey: string, toKey: string): void {
    usePendingTaskPromptStore.getState().move(fromKey, toKey);
  },
  clear(key: string): void {
    usePendingTaskPromptStore.getState().clear(key);
  },
};

export function generatePendingTaskKey(): string {
  const cryptoObj =
    typeof globalThis !== "undefined"
      ? (globalThis as { crypto?: { randomUUID?: () => string } }).crypto
      : undefined;
  if (cryptoObj?.randomUUID) {
    return cryptoObj.randomUUID();
  }
  return `pending-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
