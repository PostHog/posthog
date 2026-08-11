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
  /** The latest run id the user had in view when they made this pick. Lets
   *  the task screen prefer the server-recorded run config when a new run
   *  (possibly started on another device) has appeared since — an identity
   *  comparison, deliberately not wall clocks, so device clock skew can't
   *  flip the precedence. */
  lastSeenRunId?: string;
}

/**
 * True when the latest run's config (recorded server-side at run start) is
 * fresher than this device's local composer selection — i.e. a run the local
 * pick has not seen yet exists, e.g. the task was re-run from desktop with a
 * different model. Configs saved before this field existed count as stale.
 */
export function isRunConfigNewer(
  latestRunId: string | null | undefined,
  lastSeenRunId: string | undefined,
): boolean {
  return !!latestRunId && latestRunId !== lastSeenRunId;
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
  /** Keys of the task-list groups the user collapsed (see `taskListItems`).
   *  Persisted so the list keeps its shape across restarts. */
  collapsedGroups: string[];
  composerConfigByTaskId: Record<string, TaskComposerConfig>;
  pendingPromptByTaskId: Record<string, string>;

  selectTask: (taskId: string | null) => void;
  setOrganizeMode: (mode: OrganizeMode) => void;
  setSortMode: (mode: SortMode) => void;
  setShowInternal: (showInternal: boolean) => void;
  setFilter: (filter: string) => void;
  setLastRepository: (selection: RepositorySelection) => void;
  toggleGroupCollapsed: (groupKey: string) => void;
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
      collapsedGroups: [],
      composerConfigByTaskId: {},
      pendingPromptByTaskId: {},

      selectTask: (selectedTaskId) => set({ selectedTaskId }),
      setOrganizeMode: (organizeMode) => set({ organizeMode }),
      setSortMode: (sortMode) => set({ sortMode }),
      setShowInternal: (showInternal) => set({ showInternal }),
      setFilter: (filter) => set({ filter }),
      setLastRepository: (lastRepository) => set({ lastRepository }),
      toggleGroupCollapsed: (groupKey) =>
        set((state) => ({
          collapsedGroups: state.collapsedGroups.includes(groupKey)
            ? state.collapsedGroups.filter((key) => key !== groupKey)
            : [...state.collapsedGroups, groupKey],
        })),
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
        collapsedGroups: state.collapsedGroups,
        composerConfigByTaskId: state.composerConfigByTaskId,
      }),
    },
  ),
);
