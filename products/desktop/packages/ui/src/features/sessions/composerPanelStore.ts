import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Bounds the persisted list. A collapse only matters while its tool call still
 * waits for an answer, so the oldest ids are safe to drop.
 */
const MAX_COLLAPSED = 50;

interface ComposerPanelState {
  /**
   * Tool call ids whose composer panel the user closed, oldest first. An id
   * that is absent is expanded, so a plan or a question set arrives open.
   * Persisted because closing the panel to read the thread must survive a
   * reload while the agent still waits for the answer.
   */
  collapsedToolCallIds: string[];
  /**
   * Whether the persisted list has arrived. Reading it before then would open
   * every panel for a frame after a reload, overlay and all, so the panel
   * stays closed until the answer is known.
   */
  hasHydrated: boolean;
  setCollapsed: (toolCallId: string, collapsed: boolean) => void;
  setHasHydrated: (hydrated: boolean) => void;
}

export const useComposerPanelStore = create<ComposerPanelState>()(
  persist(
    (set) => ({
      collapsedToolCallIds: [],
      hasHydrated: false,
      setHasHydrated: (hydrated) => set({ hasHydrated: hydrated }),
      setCollapsed: (toolCallId, collapsed) =>
        set((state) => {
          const others = state.collapsedToolCallIds.filter(
            (id) => id !== toolCallId,
          );
          if (!collapsed) {
            return others.length === state.collapsedToolCallIds.length
              ? state
              : { collapsedToolCallIds: others };
          }
          return {
            collapsedToolCallIds: [...others, toolCallId].slice(-MAX_COLLAPSED),
          };
        }),
    }),
    {
      name: "composer-panel-storage",
      storage: electronStorage,
      version: 1,
      partialize: (state) => ({
        collapsedToolCallIds: state.collapsedToolCallIds,
      }),
      // Also runs when the read fails, where the store keeps its empty list.
      // A panel that opens without its remembered state is better than one
      // that can never be opened again.
      onRehydrateStorage: () => () => {
        useComposerPanelStore.setState({ hasHydrated: true });
      },
    },
  ),
);

export function useComposerPanelCollapsed(
  toolCallId: string | undefined,
): boolean {
  return useComposerPanelStore((s) => {
    if (!toolCallId) return false;
    return !s.hasHydrated || s.collapsedToolCallIds.includes(toolCallId);
  });
}

export function useSetComposerPanelCollapsed(): ComposerPanelState["setCollapsed"] {
  return useComposerPanelStore((s) => s.setCollapsed);
}
