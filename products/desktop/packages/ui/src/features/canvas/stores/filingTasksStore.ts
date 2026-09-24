import { create } from "zustand";

type FilingTaskStatus = "pending" | "complete" | "hidden";

interface FilingTask {
  channelId: string;
  status: FilingTaskStatus;
}

interface FilingTasksStore {
  filingTasks: Record<string, FilingTask | undefined>;
  startFiling: (taskId: string, channelId: string) => void;
  completeFiling: (taskId: string, channelId: string) => void;
  hideFiledTask: (taskId: string, channelId: string) => void;
  clearFiling: (taskId: string, channelId: string) => void;
}

export const useFilingTasksStore = create<FilingTasksStore>()((set) => ({
  filingTasks: {},
  startFiling: (taskId, channelId) =>
    set((state) => ({
      filingTasks: {
        ...state.filingTasks,
        [taskId]: { channelId, status: "pending" },
      },
    })),
  completeFiling: (taskId, channelId) =>
    set((state) => {
      const filing = state.filingTasks[taskId];
      if (!filing || filing.channelId !== channelId) return state;
      return {
        filingTasks: {
          ...state.filingTasks,
          [taskId]: { ...filing, status: "complete" },
        },
      };
    }),
  hideFiledTask: (taskId, channelId) =>
    set((state) => {
      const filing = state.filingTasks[taskId];
      if (!filing || filing.channelId !== channelId) return state;
      const { [taskId]: _, ...filingTasks } = state.filingTasks;
      return { filingTasks };
    }),
  clearFiling: (taskId, channelId) =>
    set((state) => {
      if (state.filingTasks[taskId]?.channelId !== channelId) return state;
      const { [taskId]: _, ...filingTasks } = state.filingTasks;
      return { filingTasks };
    }),
}));
