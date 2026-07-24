import { describe, expect, it } from "vitest";
import {
  buildStatusSummary,
  type CellStatus,
  deriveStatus,
  type SessionStatusInput,
} from "./status";

function makeSession(
  overrides: Partial<SessionStatusInput> = {},
): SessionStatusInput {
  return {
    status: "connected",
    pendingPermissions: { size: 0 },
    isPromptPending: false,
    ...overrides,
  };
}

describe("deriveStatus", () => {
  it("returns idle for no session", () => {
    expect(deriveStatus(undefined)).toBe("idle");
  });

  it("returns error for session status error", () => {
    expect(deriveStatus(makeSession({ status: "error" }))).toBe("error");
  });

  it.each(["failed", "cancelled"])(
    "returns error for cloudStatus %s",
    (cloudStatus) => {
      expect(deriveStatus(makeSession({ cloudStatus }))).toBe("error");
    },
  );

  it("returns completed for cloudStatus completed", () => {
    expect(deriveStatus(makeSession({ cloudStatus: "completed" }))).toBe(
      "completed",
    );
  });

  it("returns waiting when permissions pending", () => {
    expect(deriveStatus(makeSession({ pendingPermissions: { size: 1 } }))).toBe(
      "waiting",
    );
  });

  it("returns running when connected and prompt pending", () => {
    expect(deriveStatus(makeSession({ isPromptPending: true }))).toBe(
      "running",
    );
  });

  it("returns idle otherwise", () => {
    expect(deriveStatus(makeSession())).toBe("idle");
  });
});

describe("buildStatusSummary", () => {
  function cell(taskId: string | null, status: CellStatus) {
    return { taskId, task: taskId ? {} : undefined, status };
  }

  it("tallies populated cells by status", () => {
    const summary = buildStatusSummary([
      cell("a", "running"),
      cell("b", "waiting"),
      cell("c", "idle"),
      cell("d", "error"),
      cell("e", "completed"),
      cell(null, "idle"),
    ]);
    expect(summary).toEqual({
      total: 5,
      running: 1,
      waiting: 1,
      idle: 1,
      error: 1,
      completed: 1,
    });
  });

  it("ignores cells without a task", () => {
    const summary = buildStatusSummary([
      cell(null, "idle"),
      { taskId: "x", task: undefined, status: "running" },
    ]);
    expect(summary.total).toBe(0);
  });
});
