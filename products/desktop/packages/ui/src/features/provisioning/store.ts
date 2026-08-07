import { appendOutputChunk } from "@posthog/core/provisioning/output";
import { create } from "zustand";

interface ProvisioningStoreState {
  activeTasks: Set<string>;
  output: Record<string, string[]>;
  errors: Record<string, string>;
}

interface ProvisioningStoreActions {
  setActive: (taskId: string) => void;
  setFailed: (taskId: string, message: string) => void;
  clear: (taskId: string) => void;
  isActive: (taskId: string) => boolean;
  appendChunk: (taskId: string, chunk: string) => void;
}

type ProvisioningStore = ProvisioningStoreState & ProvisioningStoreActions;

export const useProvisioningStore = create<ProvisioningStore>()((set, get) => ({
  activeTasks: new Set(),
  output: {},
  errors: {},

  setActive: (taskId) =>
    set((state) => {
      const next = new Set(state.activeTasks);
      next.add(taskId);
      const { [taskId]: _clearedError, ...errors } = state.errors;
      return { activeTasks: next, errors };
    }),

  setFailed: (taskId, message) =>
    set((state) => {
      const next = new Set(state.activeTasks);
      next.delete(taskId);
      return {
        activeTasks: next,
        errors: { ...state.errors, [taskId]: message },
      };
    }),

  clear: (taskId) =>
    set((state) => {
      const next = new Set(state.activeTasks);
      next.delete(taskId);
      const { [taskId]: _removed, ...output } = state.output;
      const { [taskId]: _clearedError, ...errors } = state.errors;
      return { activeTasks: next, output, errors };
    }),

  isActive: (taskId) => get().activeTasks.has(taskId),

  appendChunk: (taskId, chunk) =>
    set((state) => ({
      output: {
        ...state.output,
        [taskId]: appendOutputChunk(state.output[taskId] ?? [], chunk),
      },
    })),
}));
