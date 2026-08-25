import { create } from "zustand";
import { persist } from "zustand/middleware";

// Beyond this the oldest mirrored ids are dropped. A dropped id costs one
// redundant (idempotent) PATCH on the next launch, so the cap only bounds
// storage, not correctness.
const SYNCED_IDS_CAP = 5000;

interface ServerArchiveSyncStore {
  /**
   * Archives this device has mirrored onto the server. Durable, so a backlog
   * is written once ever rather than once per launch.
   */
  syncedTaskIds: string[];
  /**
   * Restores whose server-side clear hasn't landed. Durable, because until the
   * clear lands the session is archived server-side — hidden from every list,
   * including this device's — and nothing else can rediscover it: the sync
   * pass reads the local archive, which the restore just removed it from.
   */
  pendingUnarchiveTaskIds: string[];
  markSynced: (taskId: string) => void;
  forgetSynced: (taskId: string) => void;
  queueUnarchive: (taskId: string) => void;
  clearUnarchive: (taskId: string) => void;
}

export const useServerArchiveSyncStore = create<ServerArchiveSyncStore>()(
  persist(
    (set) => ({
      syncedTaskIds: [],
      pendingUnarchiveTaskIds: [],
      markSynced: (taskId) =>
        set((state) => ({
          syncedTaskIds: [
            ...state.syncedTaskIds.filter((id) => id !== taskId),
            taskId,
          ].slice(-SYNCED_IDS_CAP),
        })),
      forgetSynced: (taskId) =>
        set((state) => ({
          syncedTaskIds: state.syncedTaskIds.filter((id) => id !== taskId),
        })),
      queueUnarchive: (taskId) =>
        set((state) =>
          state.pendingUnarchiveTaskIds.includes(taskId)
            ? state
            : {
                pendingUnarchiveTaskIds: [
                  ...state.pendingUnarchiveTaskIds,
                  taskId,
                ],
              },
        ),
      clearUnarchive: (taskId) =>
        set((state) => ({
          pendingUnarchiveTaskIds: state.pendingUnarchiveTaskIds.filter(
            (id) => id !== taskId,
          ),
        })),
    }),
    { name: "server-archive-sync" },
  ),
);
