import { create } from "zustand";

interface InboxCloudTaskStoreState {
  isRunning: boolean;
  showConfirm: boolean;
  selectedRepo: string | null;
}

interface InboxCloudTaskStoreActions {
  openConfirm: (defaultRepo: string | null) => void;
  closeConfirm: () => void;
  setSelectedRepo: (repo: string | null) => void;
  setIsRunning: (isRunning: boolean) => void;
}

type InboxCloudTaskStore = InboxCloudTaskStoreState &
  InboxCloudTaskStoreActions;

export const useInboxCloudTaskStore = create<InboxCloudTaskStore>()((set) => ({
  isRunning: false,
  showConfirm: false,
  selectedRepo: null,

  openConfirm: (defaultRepo) =>
    set({ showConfirm: true, selectedRepo: defaultRepo }),

  closeConfirm: () => set({ showConfirm: false }),

  setSelectedRepo: (repo) => set({ selectedRepo: repo }),

  setIsRunning: (isRunning) => set({ isRunning }),
}));
