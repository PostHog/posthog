import type { StoredLogEntry } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import type { CloudLogGapReconcileRequest } from "./cloudLogGap";
import {
  type CloudLogGapFetchResult,
  CloudLogGapReconciler,
  type CloudLogGapReconcilerDeps,
  type CloudLogGapReconcilerSession,
} from "./cloudLogGapReconciler";

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

function entry(method: string): StoredLogEntry {
  return {
    type: "notification",
    notification: { method },
  } as unknown as StoredLogEntry;
}

function request(
  over: Partial<CloudLogGapReconcileRequest> = {},
): CloudLogGapReconcileRequest {
  return {
    taskId: "t1",
    taskRunId: "r1",
    expectedCount: 5,
    currentCount: 0,
    newEntries: [],
    logUrl: "https://logs/r1",
    ...over,
  };
}

function createDeps(
  over: Partial<{
    fetch: CloudLogGapFetchResult;
    session: CloudLogGapReconcilerSession | undefined;
  }> = {},
) {
  const session: CloudLogGapReconcilerSession | undefined =
    over.session === undefined
      ? { taskId: "t1", processedLineCount: 0, logUrl: "https://logs/r1" }
      : over.session;

  const fetchLogs = vi.fn(
    async (): Promise<CloudLogGapFetchResult> =>
      over.fetch ?? {
        rawEntries: [entry("a"), entry("b")],
        totalLineCount: 5,
        parseFailureCount: 0,
      },
  );
  const getSession = vi.fn(() => session);
  const commit = vi.fn();
  const logger = { warn: vi.fn() };

  const deps: CloudLogGapReconcilerDeps = {
    fetchLogs,
    getSession,
    commit,
    logger,
  };
  return { deps, fetchLogs, getSession, commit, logger };
}

describe("CloudLogGapReconciler", () => {
  it("fills the gap and commits the fetched log with the resolved url", async () => {
    const { deps, commit } = createDeps({
      fetch: {
        rawEntries: [entry("a")],
        totalLineCount: 5,
        parseFailureCount: 0,
      },
    });
    new CloudLogGapReconciler(deps).reconcile(request());
    await tick();

    expect(commit).toHaveBeenCalledWith(
      "r1",
      [entry("a")],
      "https://logs/r1",
      5,
    );
  });

  it("does not commit when the store already caught up", async () => {
    const { deps, commit } = createDeps({
      session: { taskId: "t1", processedLineCount: 5, logUrl: undefined },
    });
    new CloudLogGapReconciler(deps).reconcile(request());
    await tick();

    expect(commit).not.toHaveBeenCalled();
  });

  it("does nothing when the run was swapped out from under the fetch", async () => {
    const { deps, commit } = createDeps({
      session: {
        taskId: "different",
        processedLineCount: 0,
        logUrl: undefined,
      },
    });
    new CloudLogGapReconciler(deps).reconcile(request());
    await tick();

    expect(commit).not.toHaveBeenCalled();
  });

  it("waits (no commit) when short with a fresh deficit", async () => {
    const { deps, commit, logger } = createDeps({
      fetch: {
        rawEntries: [entry("a")],
        totalLineCount: 3,
        parseFailureCount: 0,
      },
    });
    new CloudLogGapReconciler(deps).reconcile(request());
    await tick();

    expect(commit).not.toHaveBeenCalled();
    expect(logger.warn).toHaveBeenCalledWith(
      "Cloud task log count inconsistency",
      expect.objectContaining({ taskRunId: "r1" }),
    );
  });

  it("commits best-effort immediately on a parse failure", async () => {
    const { deps, commit } = createDeps({
      fetch: {
        rawEntries: [entry("a")],
        totalLineCount: 3,
        parseFailureCount: 2,
      },
    });
    new CloudLogGapReconciler(deps).reconcile(request());
    await tick();

    expect(commit).toHaveBeenCalledWith(
      "r1",
      [entry("a")],
      "https://logs/r1",
      5,
    );
  });

  it("commits best-effort once the same deficit repeats", async () => {
    const { deps, commit } = createDeps({
      fetch: {
        rawEntries: [entry("a")],
        totalLineCount: 3,
        parseFailureCount: 0,
      },
    });
    const reconciler = new CloudLogGapReconciler(deps);

    reconciler.reconcile(request());
    await tick();
    expect(commit).not.toHaveBeenCalled();

    reconciler.reconcile(request());
    await tick();
    expect(commit).toHaveBeenCalledTimes(1);
    expect(commit).toHaveBeenCalledWith(
      "r1",
      [entry("a")],
      "https://logs/r1",
      5,
    );
  });

  it("forgetting the deficit makes the next short fetch wait again", async () => {
    const { deps, commit } = createDeps({
      fetch: {
        rawEntries: [entry("a")],
        totalLineCount: 3,
        parseFailureCount: 0,
      },
    });
    const reconciler = new CloudLogGapReconciler(deps);

    reconciler.reconcile(request());
    await tick();
    reconciler.forgetDeficiency("r1");

    reconciler.reconcile(request());
    await tick();
    expect(commit).not.toHaveBeenCalled();
  });

  it("coalesces a concurrent request into a single in-flight loop", async () => {
    const { deps, fetchLogs } = createDeps();
    // Never-resolving fetch keeps the first loop in-flight.
    fetchLogs.mockImplementation(
      () => new Promise<CloudLogGapFetchResult>(() => {}),
    );
    const reconciler = new CloudLogGapReconciler(deps);

    reconciler.reconcile(request());
    reconciler.reconcile(request({ expectedCount: 8 }));
    await tick();

    expect(fetchLogs).toHaveBeenCalledTimes(1);
  });
});
