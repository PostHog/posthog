import { create } from "zustand";

interface DashboardEditState {
  // Per-dashboard edit toggle: when on, the dashboard shows its gen-UI canvas
  // + chat input instead of the dashboard tiles.
  editing: Record<string, boolean>;
  toggle: (dashboardId: string) => void;
  setEditing: (dashboardId: string, value: boolean) => void;
}

export const useDashboardEditStore = create<DashboardEditState>((set) => ({
  editing: {},
  toggle: (dashboardId) =>
    set((s) => ({
      editing: { ...s.editing, [dashboardId]: !s.editing[dashboardId] },
    })),
  setEditing: (dashboardId, value) =>
    set((s) => ({ editing: { ...s.editing, [dashboardId]: value } })),
}));

export function useIsDashboardEditing(dashboardId: string): boolean {
  return useDashboardEditStore((s) => !!s.editing[dashboardId]);
}
