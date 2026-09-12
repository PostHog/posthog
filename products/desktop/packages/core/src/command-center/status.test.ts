import type { AcpMessage } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import type { TaskTimestamp } from "../sidebar/buildSidebarData";
import {
  buildStatusSummary,
  type CellStatus,
  deriveStatus,
  deriveTaskCellStatus,
  hasUnseenCompletion,
  latestStopReason,
  type SessionStatusInput,
  trackLatestStopReason,
} from "./status";

function makeSession(
  overrides: Partial<SessionStatusInput> = {},
): SessionStatusInput {
  return {
    status: "connected",
    pendingPermissions: { size: 0 },
    isPromptPending: false,
    events: [],
    ...overrides,
  };
}

function completedTurn(stopReason: string, ts: number): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: { id: ts, result: { stopReason } },
  };
}

describe("deriveStatus", () => {
  it("returns idle for no session", () => {
    expect(deriveStatus(undefined)).toBe("idle");
  });

  it("returns error for session status error", () => {
    expect(deriveStatus(makeSession({ status: "error" }))).toBe("error");
  });

  it.each(["failed", "cancelled"] as const)(
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

  it.each<[string, AcpMessage[], CellStatus]>([
    ["cancelled", [completedTurn("cancelled", 1)], "error"],
    [
      "completed after an earlier cancellation",
      [completedTurn("cancelled", 1), completedTurn("end_turn", 2)],
      "idle",
    ],
  ])(
    "returns the correct state when the latest local turn is %s",
    (_, events, expected) => {
      expect(deriveStatus(makeSession({ events }))).toBe(expected);
    },
  );

  it("returns idle otherwise", () => {
    expect(deriveStatus(makeSession())).toBe("idle");
  });

  it.each([
    ["background", undefined, "running"],
    ["interactive", undefined, "idle"],
    [
      "interactive",
      {
        ...makeSession({ pendingPermissions: { size: 1 } }),
        taskRunId: "run-1",
      },
      "waiting",
    ],
    [
      "interactive",
      {
        ...makeSession({ status: "error", pendingPermissions: { size: 1 } }),
        taskRunId: "run-0",
      },
      "idle",
    ],
  ] as const)(
    "derives the task-aware status for a %s run",
    (mode, session, expected) => {
      expect(
        deriveTaskCellStatus(
          {
            id: "task-1",
            latest_run: {
              id: "run-1",
              status: "in_progress",
              environment: "cloud",
              mode,
            },
          },
          session,
        ),
      ).toBe(expected);
    },
  );
});

describe("hasUnseenCompletion", () => {
  it.each<[string, CellStatus, TaskTimestamp | undefined, boolean]>([
    ["local completion", "idle", { lastViewedAt: 1, lastActivityAt: 2 }, true],
    [
      "cloud completion",
      "completed",
      { lastViewedAt: 1, lastActivityAt: 2 },
      true,
    ],
    ["active work", "running", { lastViewedAt: 1, lastActivityAt: 2 }, false],
    ["input request", "waiting", { lastViewedAt: 1, lastActivityAt: 2 }, false],
    ["seen result", "idle", { lastViewedAt: 2, lastActivityAt: 1 }, false],
    ["never viewed", "idle", undefined, false],
  ])("identifies %s", (_label, status, timestamp, expected) => {
    expect(
      hasUnseenCompletion(status, "1970-01-01T00:00:00.000Z", timestamp),
    ).toBe(expected);
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

describe("trackLatestStopReason", () => {
  function chunk(ts: number): AcpMessage {
    return {
      type: "acp_message",
      ts,
      message: {
        jsonrpc: "2.0",
        method: "session/update",
        params: { update: { sessionUpdate: "agent_message_chunk" } },
      },
    };
  }

  it.each([
    {
      name: "append",
      next: (events: AcpMessage[]) => [...events, completedTurn("refusal", 9)],
    },
    {
      name: "hydrated replacement",
      next: (events: AcpMessage[]) => [
        events[0],
        completedTurn("refusal", 9),
        events[2],
      ],
    },
    { name: "truncation", next: (events: AcpMessage[]) => events.slice(0, 1) },
    { name: "eviction", next: () => [] },
  ])("agrees with a full scan after $name", ({ next }) => {
    const events = [chunk(1), completedTurn("cancelled", 2), chunk(3)];
    expect(trackLatestStopReason(events)).toBe("cancelled");
    const changed = next(events);
    expect(trackLatestStopReason(changed)).toBe(latestStopReason(changed));
  });

  it("visits only appended events while a transcript streams", () => {
    let reads = 0;
    const counted = (ts: number): AcpMessage => {
      const { message } = chunk(ts);
      return {
        type: "acp_message",
        ts,
        get message() {
          reads++;
          return message;
        },
      };
    };
    const events = [completedTurn("end_turn", 1)];
    for (let ts = 2; ts <= 200; ts++) events.push(counted(ts));
    trackLatestStopReason(events);
    reads = 0;
    for (let batch = 0; batch < 5; batch++) {
      events.push(counted(1000 + batch));
      expect(trackLatestStopReason([...events])).toBe("end_turn");
    }
    expect(reads).toBe(5);
  });
});
