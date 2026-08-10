import type { AcpMessage } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  createLatestPlanTracker,
  type SessionPlan,
  selectLatestPlan,
} from "./sessionService";

function planEvent(ts: number, title: string): AcpMessage {
  const plan: SessionPlan = {
    sessionUpdate: "plan",
    entries: [{ content: title, priority: "medium", status: "pending" }],
  };
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: { sessionId: "session-1", update: plan },
    },
  };
}

function chunkEvent(ts: number): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        sessionId: "session-1",
        update: { sessionUpdate: "agent_message_chunk", content: "hello" },
      },
    },
  };
}

function turnEndEvent(ts: number): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      id: ts,
      result: { stopReason: "end_turn" },
    },
  };
}

describe("latest plan selection", () => {
  it("returns the latest plan until the turn ends", () => {
    const events = [chunkEvent(1), planEvent(2, "Build"), chunkEvent(3)];

    expect(selectLatestPlan(events)?.entries[0]?.content).toBe("Build");
    expect(selectLatestPlan([...events, turnEndEvent(4)])).toBeNull();
  });

  it("tracker only processes newly appended events", () => {
    const first = chunkEvent(1);
    const plan = planEvent(2, "Build");
    const tracker = createLatestPlanTracker();

    expect(tracker.update([first, plan])?.entries[0]?.content).toBe("Build");

    Object.defineProperty(first, "message", {
      get() {
        throw new Error("old event was read again");
      },
    });

    expect(tracker.update([first, plan, turnEndEvent(3)])).toBeNull();
  });

  it("tracker rebuilds when the event list is replaced", () => {
    const tracker = createLatestPlanTracker();

    expect(tracker.update([planEvent(1, "First")])?.entries[0]?.content).toBe(
      "First",
    );
    expect(
      tracker.update([planEvent(2, "Replacement")])?.entries[0]?.content,
    ).toBe("Replacement");
  });

  it("tracker rebuilds when the event list is truncated", () => {
    const tracker = createLatestPlanTracker();
    const earlier = planEvent(1, "Earlier");
    const later = planEvent(2, "Later");

    expect(tracker.update([earlier, later])?.entries[0]?.content).toBe("Later");
    // Dropping the latest plan must fall back to the earlier one, matching a
    // full scan, not keep the stale append-path plan.
    const events = [earlier];
    expect(tracker.update(events)).toEqual(selectLatestPlan(events));
  });
});
