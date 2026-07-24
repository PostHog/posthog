import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ActionStatus = "running" | "success" | "error";

export function getActionSessionId(
  actionId: string,
  generation: number,
): string {
  return `action-${actionId}-${generation}`;
}

interface ActionStoreState {
  statuses: Record<string, ActionStatus>;
  generations: Record<string, number>;
}

interface ActionStoreActions {
  setStatus: (actionId: string, status: ActionStatus) => void;
  rerun: (actionId: string) => void;
  clear: (actionId: string) => void;
}

type ActionStore = ActionStoreState & ActionStoreActions;

export const useActionStore = create<ActionStore>()(
  persist(
    (set) => ({
      statuses: {},
      generations: {},

      setStatus: (actionId, status) =>
        set((state) => ({
          statuses: { ...state.statuses, [actionId]: status },
        })),

      rerun: (actionId) =>
        set((state) => {
          const { [actionId]: _, ...restStatuses } = state.statuses;
          return {
            statuses: restStatuses,
            generations: {
              ...state.generations,
              [actionId]: (state.generations[actionId] ?? 0) + 1,
            },
          };
        }),

      clear: (actionId) =>
        set((state) => {
          const { [actionId]: _s, ...restStatuses } = state.statuses;
          const { [actionId]: _g, ...restGenerations } = state.generations;
          return { statuses: restStatuses, generations: restGenerations };
        }),
    }),
    {
      name: "action-storage",
      partialize: (state) => ({
        statuses: state.statuses,
        generations: state.generations,
      }),
    },
  ),
);
