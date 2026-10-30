import { EventEmitter } from "node:events";
import type { CloudTaskEngine } from "@posthog/core/cloud-task/cloud-task-engine";
import { CloudTaskEvent } from "@posthog/core/cloud-task/schemas";
import type { CloudTaskUpdatePayload, StoredLogEntry } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import {
  applyUpdate,
  CloudRuns,
  emptyRunView,
  formatDuration,
  type RunView,
  runNotice,
  type SessionLogs,
  withListedRun,
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

  it("keeps the run's own failure reason", () => {
    const view = updates({
      kind: "status",
      status: "failed",
      errorMessage: "Sandbox failed to start",
    });
    expect(view.runError).toBe("Sandbox failed to start");
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

describe("runNotice", () => {
  const user = { kind: "user" as const, id: "u", text: "hi" };
  const reply = { kind: "assistant" as const, id: "a", text: "hello" };

  it.each([
    [
      "a queued run with only the first message",
      { status: "queued" },
      [user],
      false,
      { text: "Starting cloud run…", tone: "working" },
    ],
    [
      "a running run before any reply",
      { status: "in_progress" },
      [user],
      false,
      { text: "Starting cloud run…", tone: "working" },
    ],
    [
      "a turn in progress",
      { status: "in_progress" },
      [user, reply],
      true,
      { text: "Thinking…", tone: "working" },
    ],
    [
      "a follow-up not yet picked up",
      { status: "in_progress" },
      [user, reply, user],
      false,
      { text: "Thinking…", tone: "working" },
    ],
    [
      "an idle run that has replied",
      { status: "in_progress" },
      [user, reply],
      false,
      null,
    ],
    [
      "a failed run with a reason",
      { status: "failed", runError: "Sandbox failed to start" },
      [user],
      false,
      { text: "Sandbox failed to start", tone: "error" },
    ],
    [
      "a failed run without one",
      { status: "failed" },
      [user],
      false,
      { text: "The run failed.", tone: "error" },
    ],
    ["a finished run", { status: "completed" }, [user, reply], false, null],
  ] as const)("for %s", (_, run, lines, turnOpen, expected) => {
    expect(
      runNotice(
        { ...emptyRunView, loaded: true, ...run },
        [...lines],
        turnOpen,
        null,
      ),
    ).toEqual(expected);
  });
});

describe("withListedRun", () => {
  it("lets the work list's finished status and error win over a stream that went quiet", () => {
    const view = { ...emptyRunView, loaded: true, status: "queued" as const };
    const merged = withListedRun(view, {
      status: "failed",
      error_message: "Sandbox failed to start",
    });
    expect(merged).toMatchObject({
      status: "failed",
      runError: "Sandbox failed to start",
    });
  });

  it("keeps the stream's status while the listed run is still going", () => {
    const view = {
      ...emptyRunView,
      loaded: true,
      status: "in_progress" as const,
    };
    expect(withListedRun(view, { status: "queued" }).status).toBe(
      "in_progress",
    );
  });
});

describe("runNotice after a finished turn", () => {
  const lines = [
    { kind: "user" as const, id: "u", text: "hi" },
    { kind: "assistant" as const, id: "a", text: "hello" },
  ];
  const done = {
    durationMs: 150_000,
    endedAt: new Date(2026, 0, 1, 17, 6).getTime(),
  };

  it("says how long the agent worked and when it finished", () => {
    const notice = runNotice(
      { ...emptyRunView, loaded: true, status: "in_progress" },
      lines,
      false,
      done,
    );
    expect(notice?.tone).toBe("done");
    expect(notice?.text).toMatch(/^Worked for 2m 30s · done 5:06/);
  });

  it("gives way once a new message is waiting", () => {
    const waiting = [
      ...lines,
      { kind: "user" as const, id: "u2", text: "more" },
    ];
    expect(
      runNotice(
        { ...emptyRunView, loaded: true, status: "in_progress" },
        waiting,
        false,
        done,
      )?.text,
    ).toBe("Thinking…");
  });
});

describe("formatDuration", () => {
  it.each([
    [4_000, "4s"],
    [150_000, "2m 30s"],
    [3_720_000, "1h 2m"],
  ])("formats %d ms", (ms, text) => {
    expect(formatDuration(ms)).toBe(text);
  });
});
