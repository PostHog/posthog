import type { AcpMessage, AgentSession } from "@posthog/shared";
import { afterEach, describe, expect, it } from "vitest";
import { sessionStore, sessionStoreSetters } from "./sessionStore";

const RUN = "run-thin";
const TASK = "task-thin";

function toolUpdate(fields: Record<string, unknown>): AcpMessage {
  return {
    type: "acp_message",
    ts: 1,
    message: {
      method: "session/update",
      params: {
        update: {
          sessionUpdate: "tool_call_update",
          toolCallId: "tool-1",
          ...fields,
        },
      },
    },
  } as unknown as AcpMessage;
}

// biome-ignore lint/suspicious/noExplicitAny: test introspection
const sessionUpdate = (e: AcpMessage) => (e.message as any).params.update;

afterEach(() => sessionStoreSetters.removeSession(RUN));

describe("appendEvents — superseded snapshot thinning", () => {
  it("thins the resident previous snapshot when a newer one is appended", () => {
    sessionStoreSetters.setSession({
      taskRunId: RUN,
      taskId: TASK,
      events: [],
      messageQueue: [],
      pendingPermissions: new Map(),
      status: "connected",
    } as unknown as AgentSession);

    const first = toolUpdate({
      rawInput: { command: "ls" },
      content: "partial",
    });
    sessionStoreSetters.appendEvents(RUN, [first]);
    sessionStoreSetters.appendEvents(RUN, [
      toolUpdate({ content: "full", status: "completed" }),
    ]);

    const events = sessionStore.getState().sessions[RUN].events;
    expect(events).toHaveLength(2);
    expect(events[0]).toBe(first);
    expect(sessionUpdate(events[0])).toEqual({
      sessionUpdate: "tool_call_update",
      toolCallId: "tool-1",
      rawInput: { command: "ls" },
    });
    expect(sessionUpdate(events[1]).content).toBe("full");
  });
});
