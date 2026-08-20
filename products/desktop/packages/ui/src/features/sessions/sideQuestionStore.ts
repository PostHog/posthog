import { create } from "zustand";

export type SideQuestionStatus = "pending" | "done" | "error";

export interface SideQuestionEntry {
  id: string;
  question: string;
  answer: string;
  status: SideQuestionStatus;
  error?: string;
}

interface SideQuestionState {
  /** Latest side question per task. Ephemeral: never persisted, never part of session history. */
  byTaskId: Record<string, SideQuestionEntry>;
  ask: (taskId: string, question: string) => string;
  resolve: (taskId: string, id: string, answer: string) => void;
  fail: (taskId: string, id: string, error: string) => void;
  dismiss: (taskId: string) => void;
}

let nextId = 0;

export const useSideQuestionStore = create<SideQuestionState>()((set) => ({
  byTaskId: {},
  ask: (taskId, question) => {
    const id = `sq-${++nextId}`;
    set((state) => ({
      byTaskId: {
        ...state.byTaskId,
        [taskId]: { id, question, answer: "", status: "pending" },
      },
    }));
    return id;
  },
  resolve: (taskId, id, answer) =>
    set((state) => {
      const entry = state.byTaskId[taskId];
      if (entry?.id !== id) return state;
      return {
        byTaskId: {
          ...state.byTaskId,
          [taskId]: { ...entry, answer, status: "done" },
        },
      };
    }),
  fail: (taskId, id, error) =>
    set((state) => {
      const entry = state.byTaskId[taskId];
      if (entry?.id !== id) return state;
      return {
        byTaskId: {
          ...state.byTaskId,
          [taskId]: { ...entry, error, status: "error" },
        },
      };
    }),
  dismiss: (taskId) =>
    set((state) => {
      const { [taskId]: _dismissed, ...rest } = state.byTaskId;
      return { byTaskId: rest };
    }),
}));
