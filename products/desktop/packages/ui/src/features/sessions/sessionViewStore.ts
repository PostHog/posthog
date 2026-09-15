import type { AgentTurnFeedbackSentiment } from "@posthog/shared";
import { create } from "zustand";

interface SessionViewState {
  showRawLogs: boolean;
  searchQuery: string;
  showSearch: boolean;
  /**
   * Ephemeral per-task collapse of the queued-messages dock, keyed by taskId.
   * `true` = collapsed; absent/`false` = expanded (the default). Not persisted;
   * resets to expanded on app restart.
   */
  queueCollapsedByTaskId: Record<string, boolean>;
  /**
   * Thumbs rating given to an agent turn, keyed by turn id. Feedback is
   * analytics-only, so this exists purely to keep the chosen thumb lit —
   * without it a rated turn would forget the click as soon as the virtualized
   * thread scrolled its row out of the window. Not persisted.
   */
  turnFeedbackByTurnId: Record<string, AgentTurnFeedbackSentiment>;
  /**
   * Height in px the permission dock was last dragged to; `null` follows the
   * default share of the chat column. Kept app-wide rather than per task, since
   * someone who sizes the dock once means it for the next prompt too. Not
   * persisted.
   */
  permissionDockHeight: number | null;
}

interface SessionViewActions {
  setShowRawLogs: (show: boolean) => void;
  setSearchQuery: (query: string) => void;
  toggleSearch: () => void;
  setQueueCollapsed: (taskId: string, collapsed: boolean) => void;
  setTurnFeedback: (
    turnId: string,
    sentiment: AgentTurnFeedbackSentiment,
  ) => void;
  setPermissionDockHeight: (height: number | null) => void;
}

type SessionViewStore = SessionViewState & { actions: SessionViewActions };

const useStore = create<SessionViewStore>((set) => ({
  showRawLogs: false,
  searchQuery: "",
  showSearch: false,
  queueCollapsedByTaskId: {},
  turnFeedbackByTurnId: {},
  permissionDockHeight: null,
  actions: {
    setShowRawLogs: (show) => set({ showRawLogs: show }),
    setSearchQuery: (query) => set({ searchQuery: query }),
    toggleSearch: () =>
      set((state) => ({
        showSearch: !state.showSearch,
        searchQuery: state.showSearch ? "" : state.searchQuery,
      })),
    setQueueCollapsed: (taskId, collapsed) =>
      set((state) => ({
        queueCollapsedByTaskId: {
          ...state.queueCollapsedByTaskId,
          [taskId]: collapsed,
        },
      })),
    setTurnFeedback: (turnId, sentiment) =>
      set((state) => ({
        turnFeedbackByTurnId: {
          ...state.turnFeedbackByTurnId,
          [turnId]: sentiment,
        },
      })),
    setPermissionDockHeight: (height) => set({ permissionDockHeight: height }),
  },
}));

export const useShowRawLogs = () => useStore((s) => s.showRawLogs);
export const useSearchQuery = () => useStore((s) => s.searchQuery);
export const useShowSearch = () => useStore((s) => s.showSearch);
export const useQueueCollapsed = (taskId: string) =>
  useStore((s) => s.queueCollapsedByTaskId[taskId] ?? false);
export const usePermissionDockHeight = () =>
  useStore((s) => s.permissionDockHeight);
export const useTurnFeedback = (turnId: string) =>
  useStore((s) => s.turnFeedbackByTurnId[turnId] ?? null);
export const useSessionViewActions = () => useStore((s) => s.actions);
