import type { SessionService } from "@posthog/core/sessions/sessionService";
import { getErrorMessage } from "@posthog/shared";
import { logger } from "@posthog/ui/shell/logger";
import { create } from "zustand";

const log = logger.scope("side-question");

export type SideQuestionEntry = {
  id: string;
  question: string;
  /** The run this question was asked against — a card must not outlive it. */
  taskRunId: string;
} & (
  | { status: "pending" }
  | { status: "done"; answer: string }
  | { status: "error"; error: string }
);

interface SideQuestionState {
  /** Latest side question per task. Ephemeral: never persisted, never part of session history. */
  byTaskId: Record<string, SideQuestionEntry>;
  /** Returns null when one is already pending — the card holds a single question. */
  ask: (taskId: string, taskRunId: string, question: string) => string | null;
  resolve: (
    taskId: string,
    taskRunId: string,
    id: string,
    answer: string,
  ) => void;
  fail: (taskId: string, taskRunId: string, id: string, error: string) => void;
  dismiss: (taskId: string) => void;
}

/**
 * Settles the entry only if it is still the one the caller created for the
 * same run — a re-asked or dismissed question, or a run that reconnected or
 * restarted in the meantime, must not receive a stale answer.
 */
function settle(
  state: SideQuestionState,
  taskId: string,
  taskRunId: string,
  id: string,
  outcome:
    | { status: "done"; answer: string }
    | { status: "error"; error: string },
): Partial<SideQuestionState> | SideQuestionState {
  const entry = state.byTaskId[taskId];
  if (entry?.id !== id || entry.taskRunId !== taskRunId) return state;
  return {
    byTaskId: {
      ...state.byTaskId,
      [taskId]: {
        id: entry.id,
        question: entry.question,
        taskRunId,
        ...outcome,
      },
    },
  };
}

export const useSideQuestionStore = create<SideQuestionState>()((set, get) => ({
  byTaskId: {},
  ask: (taskId, taskRunId, question) => {
    const pending = get().byTaskId[taskId];
    if (pending?.status === "pending" && pending.taskRunId === taskRunId) {
      return null;
    }
    const id = crypto.randomUUID();
    set((state) => ({
      byTaskId: {
        ...state.byTaskId,
        [taskId]: { id, question, taskRunId, status: "pending" },
      },
    }));
    return id;
  },
  resolve: (taskId, taskRunId, id, answer) =>
    set((state) =>
      settle(state, taskId, taskRunId, id, { status: "done", answer }),
    ),
  fail: (taskId, taskRunId, id, error) =>
    set((state) =>
      settle(state, taskId, taskRunId, id, { status: "error", error }),
    ),
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
 *
 * Returns false when one is already pending, so the caller can say so rather
 * than replace a question whose answer is still on its way.
 */
export function fireSideQuestion(
  sessionService: Pick<SessionService, "askSideQuestion">,
  taskId: string,
  taskRunId: string,
  question: string,
): boolean {
  const { ask, resolve, fail } = useSideQuestionStore.getState();
  const id = ask(taskId, taskRunId, question);
  if (!id) return false;
  sessionService
    .askSideQuestion(taskId, question)
    .then((answer) => resolve(taskId, taskRunId, id, answer))
    .catch((error) => {
      fail(
        taskId,
        taskRunId,
        id,
        getErrorMessage(error) || "Side question failed",
      );
      log.error("Side question failed", error);
    });
  return true;
}
