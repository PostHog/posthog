import type {
  SessionNotification,
  SessionUpdate,
} from "@agentclientprotocol/sdk";
import type {
  AcpMessage,
  JsonRpcNotification,
  JsonRpcRequest,
} from "@posthog/shared";
import type { AgentSessionEvent } from "@posthog/shared/agent-platform-types";
import { describe, expect, it } from "vitest";
import {
  createAgentChatMapper,
  sessionEventsToAcpMessages,
} from "./sessionEventToAcp";

const TS = "2024-01-01T00:00:00.000Z";

function ev<K extends AgentSessionEvent["kind"]>(
  kind: K,
  data: Extract<AgentSessionEvent, { kind: K }>["data"],
): AgentSessionEvent {
  return { session_id: "s1", ts: TS, kind, data } as AgentSessionEvent;
}

function methodOf(m: AcpMessage): string | undefined {
  return "method" in m.message ? m.message.method : undefined;
}

function updateOf(m: AcpMessage): SessionUpdate {
  const params = (m.message as JsonRpcNotification)
    .params as SessionNotification;
  return params.update;
}

describe("createAgentChatMapper", () => {
  it("maps user messages to prompt requests with monotonic ids", () => {
    const mapper = createAgentChatMapper();
    const first = mapper.apply(ev("user_message", { text: "hi" }));
    const second = mapper.apply(ev("user_message", { text: "again" }));

    expect(methodOf(first[0])).toBe("session/prompt");
    expect((first[0].message as JsonRpcRequest).id).toBe(1);
    expect((second[0].message as JsonRpcRequest).id).toBe(2);
  });

  it("drops empty user messages", () => {
    const mapper = createAgentChatMapper();
    expect(mapper.apply(ev("user_message", { text: "" }))).toEqual([]);
  });

  it.each([
    ["exact match", "hello", "hello"],
    ["trailing newline", "hello", "hello\n"],
    ["leading spaces", "hello", "  hello"],
  ])(
    "swallows the echo of an optimistically-seeded message (%s)",
    (_, seeded, echoed) => {
      const mapper = createAgentChatMapper();
      mapper.seedUserMessage(seeded);
      expect(mapper.apply(ev("user_message", { text: echoed }))).toEqual([]);
    },
  );

  it("swallows echoes out of order across rapid sends", () => {
    const mapper = createAgentChatMapper();
    mapper.seedUserMessage("first");
    mapper.seedUserMessage("second");
    // Echoes arrive in reverse — both must dedup, neither should render.
    expect(mapper.apply(ev("user_message", { text: "second" }))).toEqual([]);
    expect(mapper.apply(ev("user_message", { text: "first" }))).toEqual([]);
  });

  it("drops a duplicate user_message the runner re-emits", () => {
    const mapper = createAgentChatMapper();
    mapper.seedUserMessage("hello");
    expect(mapper.apply(ev("user_message", { text: "hello" }))).toEqual([]);
    // The runner re-emits the same user_message later in the stream — there's
    // nothing left in `pendingOptimistic`, but we've already rendered this
    // text, so it must still be dropped.
    expect(mapper.apply(ev("user_message", { text: "hello" }))).toEqual([]);
  });

  it("maps text and thinking deltas", () => {
    const mapper = createAgentChatMapper();
    expect(
      updateOf(mapper.apply(ev("assistant_text_delta", { text: "a" }))[0]),
    ).toEqual({
      sessionUpdate: "agent_message_chunk",
      content: { type: "text", text: "a" },
    });
    expect(
      updateOf(
        mapper.apply(ev("assistant_thinking_delta", { thinking: "t" }))[0],
      ),
    ).toEqual({
      sessionUpdate: "agent_thought_chunk",
      content: { type: "text", text: "t" },
    });
  });

  it("emits tool_call on first sighting, tool_call_update on follow-up", () => {
    const mapper = createAgentChatMapper();
    const start = mapper.apply(
      ev("tool_call_start", { id: "c1", name: "@posthog/query" }),
    );
    expect(updateOf(start[0])).toMatchObject({
      sessionUpdate: "tool_call",
      toolCallId: "c1",
      title: "@posthog/query",
      status: "in_progress",
    });

    // Canonical tool_call for an already-seen id → update (merges args).
    const canonical = mapper.apply(
      ev("tool_call", { id: "c1", name: "@posthog/query", args: { sql: "x" } }),
    );
    expect(updateOf(canonical[0])).toMatchObject({
      sessionUpdate: "tool_call_update",
      toolCallId: "c1",
      rawInput: { sql: "x" },
    });
  });

  it("emits tool_call when the canonical event is the first sighting", () => {
    const mapper = createAgentChatMapper();
    const out = mapper.apply(
      ev("tool_call", { id: "c2", name: "t", args: { a: 1 } }),
    );
    expect(updateOf(out[0])).toMatchObject({
      sessionUpdate: "tool_call",
      toolCallId: "c2",
      rawInput: { a: 1 },
    });
  });

  it("maps a successful tool_result to a completed update", () => {
    const mapper = createAgentChatMapper();
    mapper.apply(ev("tool_call_start", { id: "c1", name: "t" }));
    const out = mapper.apply(
      ev("tool_result", { id: "c1", ok: true, output: { rows: 1 } }),
    );
    expect(updateOf(out[0])).toMatchObject({
      sessionUpdate: "tool_call_update",
      toolCallId: "c1",
      status: "completed",
    });
  });

  it("maps an errored tool_result to a failed update with the error text", () => {
    const mapper = createAgentChatMapper();
    mapper.apply(ev("tool_call_start", { id: "c1", name: "t" }));
    const out = mapper.apply(
      ev("tool_result", { id: "c1", ok: false, error: "boom" }),
    );
    const update = updateOf(out[0]);
    expect(update).toMatchObject({ status: "failed" });
    expect(JSON.stringify(update)).toContain("boom");
  });

  it("synthesizes a call for a tool_result with no prior start", () => {
    const mapper = createAgentChatMapper();
    const out = mapper.apply(
      ev("tool_result", {
        id: "orphan",
        tool: "mystery",
        ok: true,
        output: "ok",
      }),
    );
    expect(out).toHaveLength(2);
    expect(updateOf(out[0])).toMatchObject({
      sessionUpdate: "tool_call",
      toolCallId: "orphan",
    });
    expect(updateOf(out[1])).toMatchObject({
      sessionUpdate: "tool_call_update",
      status: "completed",
    });
  });

  it("drops streaming arg deltas, snapshots, and lifecycle frames", () => {
    const mapper = createAgentChatMapper();
    expect(mapper.apply(ev("session_started", {}))).toEqual([]);
    expect(mapper.apply(ev("turn_started", { turn: 1 }))).toEqual([]);
    expect(
      mapper.apply(ev("tool_call_args_delta", { id: "c1", argsDelta: '{"a' })),
    ).toEqual([]);
    expect(mapper.apply(ev("assistant_text", { text: "full" }))).toEqual([]);
    expect(mapper.apply(ev("closed", {}))).toEqual([]);
  });

  it("maps completed/waiting/failed to turn_complete", () => {
    const mapper = createAgentChatMapper();
    expect(methodOf(mapper.apply(ev("completed", {}))[0])).toBe(
      "_posthog/turn_complete",
    );
    expect(methodOf(mapper.apply(ev("waiting", {}))[0])).toBe(
      "_posthog/turn_complete",
    );
    const failed = mapper.apply(ev("failed", { reason: "x" }));
    expect((failed[0].message as JsonRpcNotification).params).toEqual({
      stopReason: "failed",
    });
  });

  it("folds a full streaming turn end-to-end", () => {
    const out = sessionEventsToAcpMessages([
      ev("session_started", {}),
      ev("user_message", { text: "hello" }),
      ev("turn_started", { turn: 1 }),
      ev("assistant_thinking_delta", { thinking: "let me" }),
      ev("assistant_text_delta", { text: "Hi " }),
      ev("assistant_text_delta", { text: "there" }),
      ev("tool_call_start", { id: "c1", name: "@posthog/query" }),
      ev("tool_call", { id: "c1", name: "@posthog/query", args: { sql: "1" } }),
      ev("tool_result", { id: "c1", ok: true, output: "done" }),
      ev("assistant_text", { text: "Hi there" }),
      ev("completed", {}),
    ]);

    expect(out.map(methodOf)).toEqual([
      "session/prompt",
      "session/update", // thinking
      "session/update", // text "Hi "
      "session/update", // text "there"
      "session/update", // tool_call
      "session/update", // tool_call_update (args)
      "session/update", // tool_call_update (result)
      "_posthog/turn_complete",
    ]);
  });
});
