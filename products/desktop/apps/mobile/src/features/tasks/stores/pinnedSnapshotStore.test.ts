import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  evictOldestSnapshots,
  MAX_SNAPSHOT_EVENTS,
  MAX_SNAPSHOT_TASKS,
  type PinnedSnapshot,
  retainPinnedSnapshots,
  trimSnapshotEvents,
  usePinnedSnapshotStore,
} from "./pinnedSnapshotStore";

function snapshot(savedAt: number): PinnedSnapshot {
  return { savedAt, events: [{ type: "session_update" }] };
}

function snapshots(
  entries: Record<string, number>,
): Record<string, PinnedSnapshot> {
  return Object.fromEntries(
    Object.entries(entries).map(([id, savedAt]) => [id, snapshot(savedAt)]),
  );
}

describe("trimSnapshotEvents", () => {
  it("keeps only the newest events, oldest first", () => {
    const events = Array.from({ length: MAX_SNAPSHOT_EVENTS + 5 }, (_, i) => ({
      seq: i,
    }));

    const trimmed = trimSnapshotEvents(events);

    expect(trimmed).toHaveLength(MAX_SNAPSHOT_EVENTS);
    expect(trimmed.at(0)).toEqual({ seq: 5 });
    expect(trimmed.at(-1)).toEqual({ seq: MAX_SNAPSHOT_EVENTS + 4 });
  });

  it("keeps a short thread whole", () => {
    expect(trimSnapshotEvents([{ seq: 0 }, { seq: 1 }])).toEqual([
      { seq: 0 },
      { seq: 1 },
    ]);
  });

  it("drops events that cannot survive the storage round-trip", () => {
    const circular: Record<string, unknown> = { seq: 1 };
    circular.self = circular;

    expect(trimSnapshotEvents([{ seq: 0 }, circular, { seq: 2 }])).toEqual([
      { seq: 0 },
      { seq: 2 },
    ]);
  });

  it("stores the round-tripped form, not the live object", () => {
    const [stored] = trimSnapshotEvents([
      { seq: 0, echoes: new Set(["hi"]), render: () => null },
    ]) as [Record<string, unknown>];

    // A Set serializes to `{}` and a function drops out entirely — the stored
    // event is what a relaunch would read back, so both hydration paths agree.
    expect(stored).toEqual({ seq: 0, echoes: {} });
  });
});

describe("evictOldestSnapshots", () => {
  it("leaves a store under the cap untouched", () => {
    const existing = snapshots({ a: 1, b: 2 });

    expect(evictOldestSnapshots(existing)).toBe(existing);
  });

  it("evicts the oldest savedAt past the cap", () => {
    const entries: Record<string, number> = {};
    for (let i = 0; i < MAX_SNAPSHOT_TASKS + 3; i++) {
      entries[`task-${i}`] = i;
    }

    const kept = evictOldestSnapshots(snapshots(entries));

    expect(Object.keys(kept)).toHaveLength(MAX_SNAPSHOT_TASKS);
    expect(kept["task-0"]).toBeUndefined();
    expect(kept["task-2"]).toBeUndefined();
    expect(kept["task-3"]).toBeDefined();
    expect(kept[`task-${MAX_SNAPSHOT_TASKS + 2}`]).toBeDefined();
  });
});

describe("retainPinnedSnapshots", () => {
  it("drops the snapshots of tasks that are no longer pinned", () => {
    const kept = retainPinnedSnapshots(snapshots({ a: 1, b: 2, c: 3 }), [
      "a",
      "c",
    ]);

    expect(Object.keys(kept).sort()).toEqual(["a", "c"]);
  });

  it("returns the same object when every snapshot is still pinned", () => {
    const existing = snapshots({ a: 1, b: 2 });

    expect(retainPinnedSnapshots(existing, ["a", "b", "c"])).toBe(existing);
  });

  it("clears everything when nothing is pinned", () => {
    expect(retainPinnedSnapshots(snapshots({ a: 1 }), [])).toEqual({});
  });
});

describe("usePinnedSnapshotStore", () => {
  beforeEach(() => {
    usePinnedSnapshotStore.setState({ snapshots: {} });
  });

  it("saves a trimmed snapshot stamped with the write time", () => {
    vi.spyOn(Date, "now").mockReturnValue(1_700_000_000_000);

    usePinnedSnapshotStore.getState().saveSnapshot("task-1", {
      taskTitle: "Fix the thing",
      events: [{ seq: 0 }, { seq: 1 }],
    });

    expect(usePinnedSnapshotStore.getState().snapshots["task-1"]).toEqual({
      savedAt: 1_700_000_000_000,
      taskTitle: "Fix the thing",
      events: [{ seq: 0 }, { seq: 1 }],
    });
    vi.mocked(Date.now).mockRestore();
  });

  it("refuses to overwrite a good snapshot with an empty one", () => {
    const store = usePinnedSnapshotStore.getState();
    store.saveSnapshot("task-1", { events: [{ seq: 0 }] });

    store.saveSnapshot("task-1", { events: [] });

    expect(
      usePinnedSnapshotStore.getState().snapshots["task-1"].events,
    ).toEqual([{ seq: 0 }]);
  });

  it("drops one task's snapshot on unpin", () => {
    const store = usePinnedSnapshotStore.getState();
    store.saveSnapshot("task-1", { events: [{ seq: 0 }] });
    store.saveSnapshot("task-2", { events: [{ seq: 0 }] });

    store.dropSnapshot("task-1");

    expect(Object.keys(usePinnedSnapshotStore.getState().snapshots)).toEqual([
      "task-2",
    ]);
  });

  it("keeps only the still-pinned snapshots", () => {
    const store = usePinnedSnapshotStore.getState();
    store.saveSnapshot("task-1", { events: [{ seq: 0 }] });
    store.saveSnapshot("task-2", { events: [{ seq: 0 }] });

    store.retainPinned(["task-2"]);

    expect(Object.keys(usePinnedSnapshotStore.getState().snapshots)).toEqual([
      "task-2",
    ]);
  });

  it("evicts the oldest task once the cap is exceeded", () => {
    const store = usePinnedSnapshotStore.getState();
    let clock = 1_000;
    vi.spyOn(Date, "now").mockImplementation(() => clock++);
    for (let i = 0; i <= MAX_SNAPSHOT_TASKS; i++) {
      store.saveSnapshot(`task-${i}`, { events: [{ seq: i }] });
    }

    const kept = usePinnedSnapshotStore.getState().snapshots;

    expect(Object.keys(kept)).toHaveLength(MAX_SNAPSHOT_TASKS);
    expect(kept["task-0"]).toBeUndefined();
    expect(kept[`task-${MAX_SNAPSHOT_TASKS}`]).toBeDefined();
    vi.mocked(Date.now).mockRestore();
  });
});
