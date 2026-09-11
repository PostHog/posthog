import type { AcpMessage } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  buildCloudEventSummary,
  getCloudEventSummary,
} from "./cloudToolChanges";

function update(ts: number, value: Record<string, unknown>): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: { update: value },
    },
  };
}
const text = (ts: number) =>
  update(ts, {
    sessionUpdate: "agent_message_chunk",
    content: { type: "text", text: "More text" },
  });
const tool = (ts: number, id: string) =>
  update(ts, {
    sessionUpdate: "tool_call",
    toolCallId: id,
    kind: "read",
    status: "in_progress",
    title: "Read example.ts",
  });

describe("getCloudEventSummary", () => {
  it("shares results and preserves previous snapshots while applying only tool updates", () => {
    const events = [text(1), tool(2, "read-1")];
    const first = getCloudEventSummary(events);
    expect(getCloudEventSummary(events)).toBe(first);
    const withText = [...events, text(3)];
    expect(getCloudEventSummary(withText)).toBe(first);
    const updated = [
      ...withText,
      update(4, {
        sessionUpdate: "tool_call_update",
        toolCallId: "read-1",
        status: "completed",
      }),
    ];
    const second = getCloudEventSummary(updated);
    expect(second.toolCalls.get("read-1")).toMatchObject({
      kind: "read",
      status: "completed",
      title: "Read example.ts",
    });
    expect(first.toolCalls.get("read-1")?.status).toBe("in_progress");
    expect(getCloudEventSummary(updated)).toBe(second);
  });

  it("keeps concurrent forked histories stable when they share the first event", () => {
    const first = text(1);
    const branchA = [first, tool(2, "branch-a")];
    const branchB = [first, tool(2, "branch-b")];
    const summaryA = getCloudEventSummary(branchA);
    const summaryB = getCloudEventSummary(branchB);
    expect(getCloudEventSummary(branchA)).toBe(summaryA);
    expect(getCloudEventSummary(branchB)).toBe(summaryB);
    expect(summaryA.toolCalls.has("branch-b")).toBe(false);
  });

  it.each(["truncate", "replace", "boundary", "evict"])(
    "rebuilds after %s",
    (change) => {
      const events = [text(1), tool(2, "read-1"), tool(3, "read-2")];
      getCloudEventSummary(events);
      const changed =
        change === "truncate"
          ? events.slice(0, 2)
          : change === "replace"
            ? [text(1), tool(2, "new")]
            : change === "boundary"
              ? [...events.slice(0, 2), tool(3, "replacement")]
              : [];
      expect(getCloudEventSummary(changed)).toEqual(
        buildCloudEventSummary(changed),
      );
    },
  );
});
