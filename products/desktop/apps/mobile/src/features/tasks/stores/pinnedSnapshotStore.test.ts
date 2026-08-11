import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SessionEvent } from "../types";
import {
  evictOldestSnapshots,
  MAX_SNAPSHOT_EVENTS,
  MAX_SNAPSHOT_TASKS,
  type PinnedSnapshot,
  retainPinnedSnapshots,
  trimSnapshotEvents,
  usePinnedSnapshotStore,
} from "./pinnedSnapshotStore";

/** A minimal, distinguishable session event; `seq` rides along in `ts`. */
function event(seq: number): SessionEvent {
  return { type: "acp_message", direction: "agent", ts: seq, message: { seq } };
}

function snapshot(savedAt: number): PinnedSnapshot {
  return { savedAt, events: [event(0)] };
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
    const events = Array.from({ length: MAX_SNAPSHOT_EVENTS + 5 }, (_, i) =>
      event(i),
    );

    const trimmed = trimSnapshotEvents(events);

    expect(trimmed).toHaveLength(MAX_SNAPSHOT_EVENTS);
    expect(trimmed.at(0)).toEqual(event(5));
    expect(trimmed.at(-1)).toEqual(event(MAX_SNAPSHOT_EVENTS + 4));
  });

  it("keeps a short thread whole", () => {
    expect(trimSnapshotEvents([event(0), event(1)])).toEqual([
      event(0),
      event(1),
    ]);
  });

  it("drops events that cannot survive the storage round-trip", () => {
    const circular = event(1) as SessionEvent & { self?: unknown };
    circular.self = circular;

    expect(trimSnapshotEvents([event(0), circular, event(2)])).toEqual([
      event(0),
      event(2),
    ]);
  });

  it("stores the round-tripped form, not the live object", () => {
    const [stored] = trimSnapshotEvents([
      {
        ...event(0),
        echoes: new Set(["hi"]),
        render: () => null,
      } as unknown as SessionEvent,
    ]);

    // A Set serializes to `{}` and a function drops out entirely — the stored
    // event is what a relaunch would read back, so both hydration paths agree.
    expect(stored).toEqual({ ...event(0), echoes: {} });
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
      events: [event(0), event(1)],
    });

    expect(usePinnedSnapshotStore.getState().snapshots["task-1"]).toEqual({
      savedAt: 1_700_000_000_000,
      taskTitle: "Fix the thing",
      events: [event(0), event(1)],
    });
    vi.mocked(Date.now).mockRestore();
  });

  it("refuses to overwrite a good snapshot with an empty one", () => {
    const store = usePinnedSnapshotStore.getState();
    store.saveSnapshot("task-1", { events: [event(0)] });

    store.saveSnapshot("task-1", { events: [] });

    expect(
      usePinnedSnapshotStore.getState().snapshots["task-1"].events,
    ).toEqual([event(0)]);
  });

  it("drops one task's snapshot on unpin", () => {
    const store = usePinnedSnapshotStore.getState();
    store.saveSnapshot("task-1", { events: [event(0)] });
    store.saveSnapshot("task-2", { events: [event(0)] });

    store.dropSnapshot("task-1");

    expect(Object.keys(usePinnedSnapshotStore.getState().snapshots)).toEqual([
      "task-2",
    ]);
  });

  it("keeps only the still-pinned snapshots", () => {
    const store = usePinnedSnapshotStore.getState();
    store.saveSnapshot("task-1", { events: [event(0)] });
    store.saveSnapshot("task-2", { events: [event(0)] });

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
      store.saveSnapshot(`task-${i}`, { events: [event(i)] });
    }

    const kept = usePinnedSnapshotStore.getState().snapshots;

    expect(Object.keys(kept)).toHaveLength(MAX_SNAPSHOT_TASKS);
    expect(kept["task-0"]).toBeUndefined();
    expect(kept[`task-${MAX_SNAPSHOT_TASKS}`]).toBeDefined();
    vi.mocked(Date.now).mockRestore();
  });
});

describe("snapshot byte budget", () => {
  it("drops inline data URIs from persisted events", () => {
    const event = {
      type: "session_update",
      notification: {
        update: {
          attachments: [{ uri: `data:image/png;base64,${"a".repeat(100)}` }],
        },
      },
    } as never;

    const [trimmed] = trimSnapshotEvents([event]);
    expect(JSON.stringify(trimmed)).toContain("data:dropped-from-snapshot");
    expect(JSON.stringify(trimmed)).not.toContain("base64");
  });

  it("keeps the newest events when the byte budget is exceeded", () => {
    const big = (id: number) =>
      ({
        type: "session_update",
        id,
        notification: { update: { content: { text: "x".repeat(60_000) } } },
      }) as never;
    const events = [big(1), big(2), big(3), big(4), big(5), big(6)];

    const trimmed = trimSnapshotEvents(events) as Array<{ id: number }>;
    expect(trimmed.length).toBeLessThan(6);
    expect(trimmed.at(-1)?.id).toBe(6);
  });
});
