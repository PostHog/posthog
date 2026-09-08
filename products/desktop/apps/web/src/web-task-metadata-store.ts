import { z } from "zod";
import { createRecordStore } from "./web-local-store";

// Per-device task metadata (pins + viewed/activity timestamps) for the web host,
// backed by localStorage. Desktop persists this in a local metadata service
// (workspace.getPinnedTaskIds / togglePin / getAllTaskTimestamps / markViewed /
// markUnread / markActivity). The archive flow reads pins early (getPinnedTaskIds + unpin),
// so without these the whole archive rejects — hence this store.

const taskMetadataSchema = z.object({
  pinnedAt: z.string().nullable(),
  lastViewedAt: z.string().nullable(),
  lastActivityAt: z.string().nullable(),
});

type TaskMetadata = z.infer<typeof taskMetadataSchema>;

const EMPTY: TaskMetadata = {
  pinnedAt: null,
  lastViewedAt: null,
  lastActivityAt: null,
};

const store = createRecordStore(
  "posthog-code:web-task-metadata",
  taskMetadataSchema,
);

function update(taskId: string, patch: Partial<TaskMetadata>): TaskMetadata {
  const current = store.get();
  const next = { ...(current[taskId] ?? EMPTY), ...patch };
  store.set({ ...current, [taskId]: next });
  return next;
}

export const webTaskMetadataStore = {
  getAll(): Record<string, TaskMetadata> {
    return store.get();
  },

  get(taskId: string): TaskMetadata {
    return store.get()[taskId] ?? EMPTY;
  },

  getPinnedTaskIds(): string[] {
    return Object.entries(store.get())
      .filter(([, m]) => m.pinnedAt !== null)
      .map(([taskId]) => taskId);
  },

  togglePin(taskId: string): { isPinned: boolean; pinnedAt: string | null } {
    const current = store.get()[taskId] ?? EMPTY;
    const pinnedAt = current.pinnedAt ? null : new Date().toISOString();
    update(taskId, { pinnedAt });
    return { isPinned: pinnedAt !== null, pinnedAt };
  },

  markViewed(taskId: string, activityAtMs?: number): void {
    const metadata = store.get()[taskId] ?? EMPTY;
    const storedActivityAtMs = metadata.lastActivityAt
      ? Date.parse(metadata.lastActivityAt)
      : 0;
    update(taskId, {
      lastViewedAt: new Date(
        Math.max(
          Date.now(),
          activityAtMs ?? 0,
          Number.isFinite(storedActivityAtMs) ? storedActivityAtMs : 0,
        ),
      ).toISOString(),
    });
  },

  markUnread(taskId: string, activityAtMs: number): void {
    const metadata = store.get()[taskId] ?? EMPTY;
    const storedActivityAtMs = metadata.lastActivityAt
      ? new Date(metadata.lastActivityAt).getTime()
      : 0;
    const effectiveActivityAtMs = Math.max(
      activityAtMs,
      Number.isFinite(storedActivityAtMs) ? storedActivityAtMs : 0,
    );
    update(taskId, {
      lastViewedAt: new Date(effectiveActivityAtMs - 1).toISOString(),
    });
  },

  markActivity(taskId: string): void {
    update(taskId, { lastActivityAt: new Date().toISOString() });
  },

  remove(taskId: string): void {
    const current = store.get();
    if (!(taskId in current)) return;
    const { [taskId]: _removed, ...rest } = current;
    store.set(rest);
  },
};
