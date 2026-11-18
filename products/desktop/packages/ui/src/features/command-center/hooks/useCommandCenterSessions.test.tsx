import { sessionStoreSetters } from "@posthog/core/sessions/sessionStore";
import type { AcpMessage, AgentSession } from "@posthog/shared";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useCommandCenterSessions } from "./useCommandCenterSessions";

const TASKS = ["task-1"];
const text: AcpMessage = {
  type: "acp_message",
  ts: 1,
  message: {
    jsonrpc: "2.0",
    method: "session/update",
    params: {
      update: {
        sessionUpdate: "agent_message_chunk",
        content: { type: "text", text: "Hello" },
      },
    },
  },
};
function seed(runId: string, taskId: string): void {
  sessionStoreSetters.setSession({
    taskRunId: runId,
    taskId,
    status: "connected",
    isPromptPending: true,
    events: [],
    messageQueue: [],
    pendingPermissions: new Map(),
  } as unknown as AgentSession);
}

afterEach(() => {
  cleanup();
  for (const id of ["run-1", "run-2", "run-3"])
    sessionStoreSetters.removeSession(id);
});

describe("useCommandCenterSessions", () => {
  it("ignores transcript appends and unrelated tasks without retaining transcript arrays", () => {
    seed("run-1", "task-1");
    seed("run-2", "task-2");
    let renders = 0;
    const { result } = renderHook(() => {
      renders++;
      return useCommandCenterSessions(TASKS);
    });
    const before = result.current;
    const baseline = renders;
    act(() => {
      sessionStoreSetters.appendEvents("run-1", [text]);
      sessionStoreSetters.appendEvents("run-2", [text]);
    });
    expect(renders).toBe(baseline);
    expect(result.current).toBe(before);
    expect(result.current.get("task-1")).not.toHaveProperty("events");
  });

  it("updates completion, cancellation, and replacement run status", () => {
    seed("run-1", "task-1");
    const { result } = renderHook(() => useCommandCenterSessions(TASKS));
    act(() =>
      sessionStoreSetters.updateSession("run-1", {
        pendingPermissions: new Map([
          [
            "request-1",
            {
              taskRunId: "run-1",
              receivedAt: 1,
              toolCall: { toolCallId: "tool-1" },
              options: [],
            },
          ],
        ]),
      }),
    );
    expect(result.current.get("task-1")?.pendingPermissions.size).toBe(1);

    act(() =>
      sessionStoreSetters.updateSession("run-1", { isPromptPending: false }),
    );
    expect(result.current.get("task-1")?.isPromptPending).toBe(false);
    act(() =>
      sessionStoreSetters.appendEvents("run-1", [
        {
          type: "acp_message",
          ts: 2,
          message: {
            jsonrpc: "2.0",
            id: 1,
            result: { stopReason: "cancelled" },
          },
        },
      ]),
    );
    expect(result.current.get("task-1")?.lastStopReason).toBe("cancelled");
    act(() => seed("run-3", "task-1"));
    expect(result.current.get("task-1")?.taskRunId).toBe("run-3");
    expect(result.current.get("task-1")?.isPromptPending).toBe(true);
  });
});
