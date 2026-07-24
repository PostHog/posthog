import type { StoredLogEntry } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  derivePendingPermissionRequests,
  isPermissionRequestAlreadySurfaced,
} from "./sessionService";

describe("derivePendingPermissionRequests", () => {
  const sdkSession = (taskRunId: string): StoredLogEntry => ({
    type: "notification",
    notification: {
      method: "_posthog/sdk_session",
      params: { taskRunId, sessionId: "session-1", adapter: "claude" },
    },
  });
  const runStarted = (taskRunId: string): StoredLogEntry => ({
    type: "notification",
    notification: {
      method: "_posthog/run_started",
      params: { runId: taskRunId, taskId: "task-1" },
    },
  });
  const prompt = (content: string): StoredLogEntry => ({
    type: "notification",
    notification: {
      method: "session/prompt",
      params: {
        sessionId: "session-1",
        prompt: [{ type: "text", text: content }],
      },
    },
  });
  const request = (requestId: string, toolCallId: string): StoredLogEntry => ({
    type: "notification",
    notification: {
      method: "_posthog/permission_request",
      params: {
        requestId,
        toolCallId,
        toolCall: { toolCallId, title: "Ready to code?" },
        options: [],
      },
    },
  });
  const resolved = (requestId: string): StoredLogEntry => ({
    type: "notification",
    notification: {
      method: "_posthog/permission_resolved",
      params: { requestId },
    },
  });

  it("returns only unanswered requests, carrying their requestId", () => {
    const pending = derivePendingPermissionRequests([
      request("r1", "t1"),
      resolved("r1"),
      request("r2", "t2"),
    ]);

    expect(pending.map((p) => p.requestId)).toEqual(["r2"]);
    expect(pending[0].toolCall.toolCallId).toBe("t2");
  });

  it("ignores unrelated entries and requests without a requestId", () => {
    const pending = derivePendingPermissionRequests([
      {
        type: "notification",
        notification: { method: "_posthog/console", params: {} },
      },
      {
        type: "notification",
        notification: { method: "_posthog/permission_request", params: {} },
      },
    ]);

    expect(pending).toEqual([]);
  });

  it("drops requests missing a toolCall so they never reach the handler", () => {
    const pending = derivePendingPermissionRequests([
      {
        type: "notification",
        notification: {
          method: "_posthog/permission_request",
          params: { requestId: "r1", options: [] },
        },
      },
    ]);

    expect(pending).toEqual([]);
  });

  it("ignores predecessor-run questions when deriving pending requests for a resumed run", () => {
    const pending = derivePendingPermissionRequests(
      [
        sdkSession("run-before"),
        runStarted("run-before"),
        request("r1", "t1"),
        sdkSession("run-after"),
        runStarted("run-after"),
        prompt(
          "This is the user's selected answer to the AskUserQuestion prompt that was pending before this cloud run resumed.",
        ),
      ],
      { taskRunId: "run-after" },
    );

    expect(pending).toEqual([]);
  });

  it("keeps current-run questions when scoped derivation matches the run", () => {
    const pending = derivePendingPermissionRequests(
      [sdkSession("run-1"), runStarted("run-1"), request("r1", "t1")],
      { taskRunId: "run-1" },
    );

    expect(pending.map((p) => p.requestId)).toEqual(["r1"]);
  });
});

describe("isPermissionRequestAlreadySurfaced", () => {
  const update = (requestId: string, toolCallId: string) => ({
    requestId,
    toolCall: { toolCallId, title: "Ready to code?", kind: "execute" },
    options: [],
  });

  it.each([
    {
      name: "same request still pending is a snapshot re-surface",
      pendingToolCallIds: ["t1"],
      trackedRequestId: "r1",
      expected: true,
    },
    {
      name: "request never surfaced notifies",
      pendingToolCallIds: [],
      trackedRequestId: undefined,
      expected: false,
    },
    {
      name: "new requestId for the same tool call is a new ask",
      pendingToolCallIds: ["t1"],
      trackedRequestId: "r0",
      expected: false,
    },
    {
      name: "tracked id without a pending entry notifies again",
      pendingToolCallIds: [],
      trackedRequestId: "r1",
      expected: false,
    },
  ])("$name", ({ pendingToolCallIds, trackedRequestId, expected }) => {
    const pendingPermissions = new Map(
      pendingToolCallIds.map((id) => [id, {}]),
    );

    expect(
      isPermissionRequestAlreadySurfaced(
        pendingPermissions,
        trackedRequestId,
        update("r1", "t1"),
      ),
    ).toBe(expected);
  });
});
