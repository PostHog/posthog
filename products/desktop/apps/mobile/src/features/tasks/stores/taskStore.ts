import type { TaskActivitySortMode } from "@posthog/core/tasks/taskActivity";
import type {
  Adapter,
  ExecutionMode,
  SupportedReasoningEffort,
} from "@posthog/shared";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type { ContextWindow } from "../composer/options";
import type { RepositorySelection } from "../types";

export type OrganizeMode = "by-project" | "chronological";
export type SortMode = TaskActivitySortMode;

const EMPTY_REPOSITORY_SELECTION: RepositorySelection = {
  integrationId: null,
  repository: null,
};

/** Per-task chat composer pill values. Persisted so reopening a task keeps
 *  the mode/model/reasoning the user last selected for it. */
export interface TaskComposerConfig {
  adapter?: Adapter;
  mode?: ExecutionMode;
  model?: string;
  reasoning?: SupportedReasoningEffort;
  contextWindow?: ContextWindow;
  fastMode?: boolean;
}

interface TaskUIState {
  selectedTaskId: string | null;
  organizeMode: OrganizeMode;
  sortMode: SortMode;
  showInternal: boolean;
  filter: string;
  /** Most-recently-used repository for the new-task composer. Pre-fills the
   *  repo pill so users don't have to re-pick the same repo every time. */
  lastRepository: RepositorySelection;
  composerConfigByTaskId: Record<string, TaskComposerConfig>;
  pendingPromptByTaskId: Record<string, string>;

  selectTask: (taskId: string | null) => void;
  setOrganizeMode: (mode: OrganizeMode) => void;
  setSortMode: (mode: SortMode) => void;
  setShowInternal: (showInternal: boolean) => void;
  setFilter: (filter: string) => void;
  setLastRepository: (selection: RepositorySelection) => void;
  setComposerConfig: (
    taskId: string,
    config: Partial<TaskComposerConfig>,
  ) => void;
  setPendingPrompt: (taskId: string, prompt: string) => void;
  consumePendingPrompt: (taskId: string) => string | undefined;
}

export const useTaskStore = create<TaskUIState>()(
  persist(
    (set, get) => ({
      selectedTaskId: null,
      organizeMode: "by-project",
      sortMode: "updated",
      showInternal: false,
      filter: "",
      lastRepository: EMPTY_REPOSITORY_SELECTION,
      composerConfigByTaskId: {},
      pendingPromptByTaskId: {},

      selectTask: (selectedTaskId) => set({ selectedTaskId }),
      setOrganizeMode: (organizeMode) => set({ organizeMode }),
      setSortMode: (sortMode) => set({ sortMode }),
      setShowInternal: (showInternal) => set({ showInternal }),
      setFilter: (filter) => set({ filter }),
      setLastRepository: (lastRepository) => set({ lastRepository }),
      setComposerConfig: (taskId, config) =>
        set((state) => ({
          composerConfigByTaskId: {
            ...state.composerConfigByTaskId,
            [taskId]: {
              ...state.composerConfigByTaskId[taskId],
              ...config,
            },
          },
        })),
      setPendingPrompt: (taskId, prompt) =>
        set((state) => ({
          pendingPromptByTaskId: {
            ...state.pendingPromptByTaskId,
            [taskId]: prompt,
          },
        })),
      consumePendingPrompt: (taskId) => {
        const prompt = get().pendingPromptByTaskId[taskId];
        if (!prompt) return undefined;
        set((state) => {
          const remaining = { ...state.pendingPromptByTaskId };
          delete remaining[taskId];
          return { pendingPromptByTaskId: remaining };
        });
        return prompt;
      },
    }),
    {
      name: "posthog-task-ui",
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (state) => ({
        organizeMode: state.organizeMode,
        sortMode: state.sortMode,
        showInternal: state.showInternal,
        lastRepository: state.lastRepository,
        composerConfigByTaskId: state.composerConfigByTaskId,
      }),
    },
  ),
);
