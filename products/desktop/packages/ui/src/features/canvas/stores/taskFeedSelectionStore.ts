import { create } from "zustand";

export interface TaskFeedSelection {
  feedId: string;
  taskId: string;
  channelId: string | null;
}

interface TaskFeedSelectionState {
  selected: TaskFeedSelection | null;
  select: (selection: TaskFeedSelection | null) => void;
}

export const useTaskFeedSelectionStore = create<TaskFeedSelectionState>()(
  (set) => ({
    selected: null,
    select: (selected) => set({ selected }),
  }),
);

export function useTaskFeedSelection(feedId: string): TaskFeedSelection | null {
  const selected = useTaskFeedSelectionStore((state) => state.selected);
  return selected?.feedId === feedId ? selected : null;
}
