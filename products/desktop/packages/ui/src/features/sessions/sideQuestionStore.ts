import type { SessionService } from "@posthog/core/sessions/sessionService";
import { getErrorMessage } from "@posthog/shared";
import { logger } from "@posthog/ui/shell/logger";
import { create } from "zustand";

const log = logger.scope("side-question");

export type SideQuestionEntry = { id: string; question: string } & (
  | { status: "pending" }
  | { status: "done"; answer: string }
  | { status: "error"; error: string }
);

interface SideQuestionState {
  /** Latest side question per task. Ephemeral: never persisted, never part of session history. */
  byTaskId: Record<string, SideQuestionEntry>;
  ask: (taskId: string, question: string) => string;
  resolve: (taskId: string, id: string, answer: string) => void;
  fail: (taskId: string, id: string, error: string) => void;
  dismiss: (taskId: string) => void;
}

/**
 * Settles the entry only if it is still the one the caller created — a
 * re-asked or dismissed question must not receive a stale answer.
 */
function settle(
  state: SideQuestionState,
  taskId: string,
  id: string,
  outcome:
    | { status: "done"; answer: string }
    | { status: "error"; error: string },
): Partial<SideQuestionState> | SideQuestionState {
  const entry = state.byTaskId[taskId];
  if (entry?.id !== id) return state;
  return {
    byTaskId: {
      ...state.byTaskId,
      [taskId]: { id: entry.id, question: entry.question, ...outcome },
    },
  };
}

export const useSideQuestionStore = create<SideQuestionState>()((set) => ({
  byTaskId: {},
  ask: (taskId, question) => {
    const id = crypto.randomUUID();
    set((state) => ({
      byTaskId: {
        ...state.byTaskId,
        [taskId]: { id, question, status: "pending" },
      },
    }));
    return id;
  },
  resolve: (taskId, id, answer) =>
    set((state) => settle(state, taskId, id, { status: "done", answer })),
  fail: (taskId, id, error) =>
    set((state) => settle(state, taskId, id, { status: "error", error })),
  dismiss: (taskId) =>
    set((state) => {
      const { [taskId]: _dismissed, ...rest } = state.byTaskId;
      return { byTaskId: rest };
    }),
}));

/**
 * Fire-and-forget "/btw" saga: record the pending entry, send the question,
 * and settle the entry with the answer or error. Fire-and-forget so the
 * composer clears immediately; the side question runs beside the
 * conversation, mid-turn or idle.
 */
export function fireSideQuestion(
  sessionService: Pick<SessionService, "askSideQuestion">,
  taskId: string,
  question: string,
): void {
  const { ask, resolve, fail } = useSideQuestionStore.getState();
  const id = ask(taskId, question);
  sessionService
    .askSideQuestion(taskId, question)
    .then((answer) => resolve(taskId, id, answer))
    .catch((error) => {
      fail(taskId, id, getErrorMessage(error) || "Side question failed");
      log.error("Side question failed", error);
    });
}
