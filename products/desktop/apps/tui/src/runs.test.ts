import { EventEmitter } from "node:events";
import type { CloudTaskEngine } from "@posthog/core/cloud-task/cloud-task-engine";
import { CloudTaskEvent } from "@posthog/core/cloud-task/schemas";
import type { CloudTaskUpdatePayload, StoredLogEntry } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import { applyUpdate, CloudRuns, emptyRunView, type RunView } from "./runs";

const entry = (id: string): StoredLogEntry => ({ type: "pi_event", id });
const base = { taskId: "t1", runId: "r1" };
const updates = (...payloads: Partial<CloudTaskUpdatePayload>[]): RunView =>
  payloads.reduce<RunView>(
    (view, payload) =>
      applyUpdate(view, { ...base, ...payload } as CloudTaskUpdatePayload),
    emptyRunView,
  );

describe("applyUpdate", () => {
  it("starts from the snapshot and appends later log entries", () => {
    const view = updates(
      {
        kind: "snapshot",
        newEntries: [entry("a"), entry("b")],
        totalEntryCount: 2,
        status: "in_progress",
        sandboxAlive: true,
      },
      { kind: "logs", newEntries: [entry("c")], totalEntryCount: 3 },
    );
    expect(view.entries.map((e) => e.id)).toEqual(["a", "b", "c"]);
    expect(view).toMatchObject({
      loaded: true,
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
    });
  });
});

describe("CloudRuns", () => {
  it("delivers only the watched run's updates and stops watching on unsubscribe", async () => {
    const engine = Object.assign(new EventEmitter(), {
      watch: vi.fn(),
      unwatch: vi.fn(),
    });
    const runs = new CloudRuns(
      engine as unknown as CloudTaskEngine,
      async () => ({ apiHost: "https://us.posthog.com", teamId: 2 }),
    );
    const seen: RunView[] = [];

    const stop = runs.watch("t1", "r1", (view) => seen.push(view));
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
    stop();

    expect(seen.map((view) => view.entries.map((e) => e.id))).toEqual([["a"]]);
    expect(engine.unwatch).toHaveBeenCalledWith("t1", "r1");
  });
});
