import { usePinnedSnapshotSync } from "../hooks/usePinnedSnapshotSync";

/**
 * Mount point for the pinned-task snapshot cache. Lives at the app root rather
 * than on the task screen so a snapshot is still written for a session whose
 * screen is being torn down.
 */
export function PinnedSnapshotSync(): null {
  usePinnedSnapshotSync();
  return null;
}
