import type { AcpMessage, AgentSession } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { CloudRunIdleTracker } from "./cloudRunIdleTracker";

function runStarted(runId: string): AcpMessage {
  return {
    type: "acp_message",
    ts: 1,
    message: {
      jsonrpc: "2.0",
      method: "_posthog/run_started",
      params: { runId },
    },
  } as AcpMessage;
}

function turnComplete(): AcpMessage {
  return {
    type: "acp_message",
    ts: 2,
    message: { jsonrpc: "2.0", method: "_posthog/turn_complete", params: {} },
  } as AcpMessage;
}

function promptRequest(id = 1): AcpMessage {
  return {
    type: "acp_message",
    ts: 3,
    message: { jsonrpc: "2.0", id, method: "session/prompt", params: {} },
  } as AcpMessage;
}

function session(
  taskRunId: string,
  events: AcpMessage[],
  agentIdleForRunId?: string,
): AgentSession {
  return { taskRunId, events, agentIdleForRunId } as AgentSession;
}

describe("CloudRunIdleTracker.evaluateIdle", () => {
  it("uses the agentIdleForRunId fast path without caching", () => {
    const tracker = new CloudRunIdleTracker();
    const result = tracker.evaluateIdle(session("r1", [], "r1"));

    expect(result).toEqual({ idle: true, shouldCacheToStore: false });
  });

  it("reports idle after a run_started then turn_complete", () => {
    const tracker = new CloudRunIdleTracker();
    const result = tracker.evaluateIdle(
      session("r1", [runStarted("r1"), turnComplete()]),
    );

    expect(result).toEqual({ idle: true, shouldCacheToStore: true });
  });

  it("reports busy when a prompt follows the last turn_complete", () => {
    const tracker = new CloudRunIdleTracker();
    const result = tracker.evaluateIdle(
      session("r1", [runStarted("r1"), turnComplete(), promptRequest()]),
    );

    expect(result.idle).toBe(false);
  });

  it("ignores events before the current run's run_started", () => {
    const tracker = new CloudRunIdleTracker();
    // turn_complete before run_started should not count as idle
    const result = tracker.evaluateIdle(
      session("r1", [turnComplete(), runStarted("r1")]),
    );

    expect(result.idle).toBe(false);
  });

  it("scans incrementally across calls", () => {
    const tracker = new CloudRunIdleTracker();
    const events = [runStarted("r1"), promptRequest()];

    expect(tracker.evaluateIdle(session("r1", events)).idle).toBe(false);

    events.push(turnComplete());
    expect(tracker.evaluateIdle(session("r1", events)).idle).toBe(true);
  });
});

describe("CloudRunIdleTracker mark/capture/restore", () => {
  it("markIdle then capture reflects an idle scan state", () => {
    const tracker = new CloudRunIdleTracker();
    const s = session("r1", [runStarted("r1")]);
    tracker.markIdle(s);

    const snapshot = tracker.capture(s);
    expect(snapshot.taskRunId).toBe("r1");
    expect(snapshot.scanState?.idle).toBe(true);
  });

  it("restoreAfterFailedSend restores prior evidence when no new prompt arrived", () => {
    const tracker = new CloudRunIdleTracker();
    const before = session("r1", [runStarted("r1")], "r1");
    tracker.markIdle(before);
    const snapshot = tracker.capture(before);

    // Simulate a failed send: markBusy advanced the marker, no new events.
    tracker.markBusy(before);
    const restored = tracker.restoreAfterFailedSend(snapshot, before);

    expect(restored).toEqual({ agentIdleForRunId: "r1" });
    expect(tracker.capture(before).scanState?.idle).toBe(true);
  });

  it("does not restore when a new prompt arrived after the snapshot", () => {
    const tracker = new CloudRunIdleTracker();
    const before = session("r1", [runStarted("r1")], "r1");
    tracker.markIdle(before);
    const snapshot = tracker.capture(before);

    const after = session("r1", [runStarted("r1"), promptRequest()], "r1");
    tracker.markBusy(after);
    expect(tracker.restoreAfterFailedSend(snapshot, after)).toBeUndefined();
  });

  it("delete and clear drop tracked state", () => {
    const tracker = new CloudRunIdleTracker();
    const s = session("r1", [runStarted("r1")]);
    tracker.markBusy(s);
    tracker.delete("r1");
    // After delete, evaluateIdle re-scans from scratch.
    expect(tracker.evaluateIdle(session("r1", [])).idle).toBe(false);
  });
});
