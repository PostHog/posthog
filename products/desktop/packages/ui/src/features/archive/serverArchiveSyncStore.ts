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
  /** Next archived-task offset to import for each account and project. */
  archiveImportOffsets: Record<string, number>;
  markSynced: (taskId: string) => void;
  forgetSynced: (taskId: string) => void;
  queueUnarchive: (taskId: string) => void;
  clearUnarchive: (taskId: string) => void;
  setArchiveImportOffset: (serverArchiveScope: string, offset: number) => void;
}

export const useServerArchiveSyncStore = create<ServerArchiveSyncStore>()(
  persist(
    (set) => ({
      syncedTaskIds: [],
      pendingUnarchiveTaskIds: [],
      archiveImportOffsets: {},
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
      setArchiveImportOffset: (serverArchiveScope, offset) =>
        set((state) => ({
          archiveImportOffsets: {
            ...state.archiveImportOffsets,
            [serverArchiveScope]: offset,
          },
        })),
    }),
    { name: "server-archive-sync" },
  ),
);
