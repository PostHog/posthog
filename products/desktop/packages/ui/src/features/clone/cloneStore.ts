import type {
  CloneOperation,
  CloneProgressEvent,
} from "@posthog/core/clone/cloneTypes";
import { create } from "zustand";

export type {
  CloneOperation,
  CloneProgressEvent,
  CloneRepositoryInput,
  CloneStatus,
} from "@posthog/core/clone/cloneTypes";

interface CloneStore {
  operations: Record<string, CloneOperation>;
  beginClone: (cloneId: string, repository: string, targetPath: string) => void;
  applyProgress: (event: CloneProgressEvent) => void;
  removeClone: (cloneId: string) => void;
}

export const cloneStore = create<CloneStore>((set) => ({
  operations: {},

  beginClone: (cloneId, repository, targetPath) => {
    set((state) => ({
      operations: {
        ...state.operations,
        [cloneId]: {
          cloneId,
          repository,
          targetPath,
          status: "cloning",
          latestMessage: `Cloning ${repository}...`,
        },
      },
    }));
  },

  applyProgress: (event) => {
    set((state) => {
      const operation = state.operations[event.cloneId];
      if (!operation) return state;

      return {
        operations: {
          ...state.operations,
          [event.cloneId]: {
            ...operation,
            status: event.status,
            latestMessage: event.message,
            error: event.status === "error" ? event.message : operation.error,
          },
        },
      };
    });
  },

  removeClone: (cloneId) => {
    set((state) => {
      const { [cloneId]: _removed, ...remainingOps } = state.operations;
      return { operations: remainingOps };
    });
  },
}));
