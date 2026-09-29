import { EventEmitter } from "node:events";
import type { CloudTaskEngine } from "@posthog/core/cloud-task/cloud-task-engine";
import { CloudTaskEvent } from "@posthog/core/cloud-task/schemas";
import type { CloudTaskUpdatePayload, StoredLogEntry } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import {
  applyUpdate,
  CloudRuns,
  emptyRunView,
  type RunView,
  type SessionLogs,
} from "./runs";

const entry = (id: string): StoredLogEntry => ({ type: "pi_event", id });
const ids = (view: RunView): string[] => view.entries.map((e) => e.id ?? "");
const base = { taskId: "t1", runId: "r1" };
const updates = (...payloads: Partial<CloudTaskUpdatePayload>[]): RunView =>
  payloads.reduce<RunView>(
    (view, payload) =>
      applyUpdate(view, { ...base, ...payload } as CloudTaskUpdatePayload),
    emptyRunView,
  );

// A run log of `total` entries named e0..e{total-1}, served like the session_logs endpoint.
function logOf(total: number): SessionLogs {
  return vi.fn(async (_taskId, _runId, { limit, offset = 0 }) => {
    const entries = Array.from(
      { length: Math.max(0, Math.min(limit, total - offset)) },
      (_, i) => entry(`e${offset + i}`),
    );
    return {
      entries,
      hasMore: offset + entries.length < total,
      matchingCount: total,
    };
  });
}

function setup(sessionLogs: SessionLogs = logOf(0)) {
  const engine = Object.assign(new EventEmitter(), {
    watch: vi.fn(),
    unwatch: vi.fn(),
  });
  const runs = new CloudRuns(
    engine as unknown as CloudTaskEngine,
    async () => ({ apiHost: "https://us.posthog.com", teamId: 2 }),
    sessionLogs,
  );
  return { engine, runs };
}

describe("applyUpdate", () => {
  it("starts from the snapshot window and appends later log entries", () => {
    const view = updates(
      {
        kind: "snapshot",
        newEntries: [entry("a"), entry("b")],
        totalEntryCount: 12,
        windowStart: 10,
        status: "in_progress",
        sandboxAlive: true,
      },
      { kind: "logs", newEntries: [entry("c")], totalEntryCount: 13 },
    );
    expect(ids(view)).toEqual(["a", "b", "c"]);
    expect(view).toMatchObject({
      loaded: true,
      windowStart: 10,
      status: "in_progress",
      sandboxAlive: true,
      error: null,
    });
  });

  it("tracks status changes and stream errors", () => {
    const view = updates(
      {
        kind: "snapshot",
        newEntries: [],
        totalEntryCount: 0,
        status: "in_progress",
      },
      { kind: "status", status: "failed", sandboxAlive: false },
      {
        kind: "error",
        errorTitle: "Stream lost",
        errorMessage: "Reconnect failed",
        retryable: true,
      },
    );
    expect(view).toMatchObject({
      status: "failed",
      sandboxAlive: false,
      error: "Stream lost: Reconnect failed",
      windowStart: 0,
    });
  });
});

describe("CloudRuns", () => {
  it("delivers only the watched run's updates and stops watching on unsubscribe", async () => {
    const { engine, runs } = setup();
    const seen: RunView[] = [];

    const run = runs.watch("t1", "r1", (view) => seen.push(view));
    await vi.waitFor(() =>
      expect(engine.watch).toHaveBeenCalledWith({
        ...base,
        apiHost: "https://us.posthog.com",
        teamId: 2,
      }),
    );
    engine.emit(CloudTaskEvent.Update, {
      taskId: "t2",
      runId: "r9",
      kind: "logs",
      newEntries: [entry("x")],
      totalEntryCount: 1,
    });
    engine.emit(CloudTaskEvent.Update, {
      ...base,
      kind: "logs",
      newEntries: [entry("a")],
      totalEntryCount: 1,
    });
    run.stop();

    expect(seen.map(ids)).toEqual([["a"]]);
    expect(engine.unwatch).toHaveBeenCalledWith("t1", "r1");
  });

  it("pages older entries in above the window until it reaches the start", async () => {
    const { engine, runs } = setup(logOf(8));
    let latest = emptyRunView;
    const run = runs.watch(
      "t1",
      "r1",
      (view) => {
        latest = view;
      },
      { olderPageSize: 3 },
    );
    engine.emit(CloudTaskEvent.Update, {
      ...base,
      kind: "snapshot",
      newEntries: [entry("e6"), entry("e7")],
      totalEntryCount: 8,
      windowStart: 6,
    });

    await run.loadOlder();
    expect(ids(latest)).toEqual(["e3", "e4", "e5", "e6", "e7"]);
    expect(latest.windowStart).toBe(3);

    await run.loadOlder();
    await run.loadOlder();
    expect(ids(latest)[0]).toBe("e0");
    expect(latest.windowStart).toBe(0);
    run.stop();
  });

  it("shows a prefetched tail as soon as a run is opened", async () => {
    const { runs } = setup(logOf(500));
    await runs.prefetch("t1", "r1", 300);
    const seen: RunView[] = [];

    runs.watch("t1", "r1", (view) => seen.push(view)).stop();

    expect(seen[0]).toMatchObject({ loaded: true, windowStart: 200 });
    expect(ids(seen[0])).toHaveLength(300);
    expect(ids(seen[0]).at(-1)).toBe("e499");
  });
});
