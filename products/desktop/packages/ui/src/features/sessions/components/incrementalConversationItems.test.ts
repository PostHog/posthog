import type { AcpMessage } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  type BuildResult,
  buildConversationItems,
  type ConversationItem,
  type TurnContext,
} from "./buildConversationItems";
import { createIncrementalConversationBuilder } from "./incrementalConversationItems";

// --- event builders -------------------------------------------------------

function updateMsg(ts: number, update: unknown): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: { jsonrpc: "2.0", method: "session/update", params: { update } },
  };
}

function userPromptMsg(ts: number, id: number, text: string): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      id,
      method: "session/prompt",
      params: { prompt: [{ type: "text", text }] },
    },
  };
}

function promptResponseMsg(
  ts: number,
  id: number,
  stopReason = "end_turn",
): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: { jsonrpc: "2.0", id, result: { stopReason } },
  };
}

function turnCompleteMsg(ts: number, stopReason = "end_turn"): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "_posthog/turn_complete",
      params: { sessionId: "s", stopReason },
    },
  };
}

function consoleMsg(ts: number, message: string, level = "info"): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "_posthog/console",
      params: { level, message },
    },
  };
}

function progressMsg(
  ts: number,
  step: string,
  status: string,
  label: string,
  group = "setup",
): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "_posthog/progress",
      params: { step, status, label, group },
    },
  };
}

function shellExecuteMsg(ts: number, id: string, command: string): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "_array/user_shell_execute",
      params: { id, command, cwd: "/repo" },
    },
  };
}

const agentChunk = (ts: number, text: string) =>
  updateMsg(ts, {
    sessionUpdate: "agent_message_chunk",
    content: { type: "text", text },
  });

const thoughtChunk = (ts: number, text: string) =>
  updateMsg(ts, {
    sessionUpdate: "agent_thought_chunk",
    content: { type: "text", text },
  });

const toolCallMsg = (
  ts: number,
  toolCallId: string,
  extra: Record<string, unknown> = {},
) =>
  updateMsg(ts, {
    sessionUpdate: "tool_call",
    toolCallId,
    kind: "execute",
    status: "pending",
    title: toolCallId,
    ...extra,
  });

const toolUpdateMsg = (
  ts: number,
  toolCallId: string,
  extra: Record<string, unknown>,
) => updateMsg(ts, { sessionUpdate: "tool_call_update", toolCallId, ...extra });

const childToolCallMsg = (
  ts: number,
  toolCallId: string,
  parentToolCallId: string,
) =>
  updateMsg(ts, {
    sessionUpdate: "tool_call",
    toolCallId,
    kind: "read",
    status: "pending",
    title: toolCallId,
    _meta: { claudeCode: { parentToolCallId } },
  });

const childThoughtChunk = (
  ts: number,
  text: string,
  parentToolCallId: string,
) =>
  updateMsg(ts, {
    sessionUpdate: "agent_thought_chunk",
    content: { type: "text", text },
    _meta: {
      posthog: {
        toolName: "subagent_activity",
        parentToolCallId,
      },
    },
  });

// --- normalization (cycle-free, Map-resolved) -----------------------------

function normContext(ctx: TurnContext) {
  return {
    turnComplete: ctx.turnComplete,
    turnCancelled: ctx.turnCancelled,
    toolCalls: [...ctx.toolCalls.entries()].sort(byKey),
    childItems: [...ctx.childItems.entries()]
      .sort(byKey)
      .map(([k, arr]) => [k, arr.map(normChild)]),
  };
}

function byKey(a: [string, unknown], b: [string, unknown]) {
  return a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0;
}

function normChild(item: ConversationItem) {
  if (item.type === "session_update") {
    const { turnContext: _drop, ...rest } = item;
    return rest;
  }
  return item;
}

function normItem(item: ConversationItem) {
  if (item.type === "session_update") {
    const { turnContext, ...rest } = item;
    return { ...rest, turnContext: normContext(turnContext) };
  }
  return item;
}

function normalize(result: BuildResult) {
  return {
    items: result.items.map(normItem),
    lastTurnInfo: result.lastTurnInfo,
    isCompacting: result.isCompacting,
    completedToolCallCount: result.completedToolCallCount,
  };
}

function assertEquivalentAcrossPrefixes(
  events: AcpMessage[],
  isPromptPending: boolean | null,
) {
  const inc = createIncrementalConversationBuilder();
  for (let k = 1; k <= events.length; k++) {
    const prefix = events.slice(0, k);
    const incremental = inc.update(prefix, isPromptPending);
    const full = buildConversationItems(prefix, isPromptPending);
    expect(normalize(incremental)).toEqual(normalize(full));
  }
}

// --- scenarios ------------------------------------------------------------

const SCENARIOS: Record<string, AcpMessage[]> = {
  "single local turn": [
    userPromptMsg(1, 1, "hello"),
    agentChunk(2, "hi "),
    agentChunk(3, "there"),
    promptResponseMsg(4, 1),
  ],
  "multi-turn with tools": [
    userPromptMsg(1, 1, "do a thing"),
    thoughtChunk(2, "thinking..."),
    agentChunk(3, "working "),
    toolCallMsg(4, "t1"),
    toolUpdateMsg(5, "t1", {
      status: "completed",
      content: [{ type: "content", content: { type: "text", text: "ok" } }],
    }),
    agentChunk(6, "done"),
    promptResponseMsg(7, 1),
    userPromptMsg(8, 2, "another"),
    agentChunk(9, "second turn"),
    promptResponseMsg(10, 2),
  ],
  "implicit cloud turn": [
    agentChunk(1, "streaming "),
    agentChunk(2, "without "),
    agentChunk(3, "a prompt"),
    turnCompleteMsg(4),
  ],
  "parent tool with children": [
    userPromptMsg(1, 1, "spawn agent"),
    toolCallMsg(2, "task1", { _meta: { claudeCode: { toolName: "Task" } } }),
    childToolCallMsg(3, "child1", "task1"),
    childToolCallMsg(4, "child2", "task1"),
    toolUpdateMsg(5, "task1", { status: "completed" }),
    promptResponseMsg(6, 1),
  ],
  "progress single group": [
    userPromptMsg(1, 1, "setup"),
    progressMsg(2, "a", "in_progress", "Step A"),
    progressMsg(3, "b", "in_progress", "Step B"),
    progressMsg(4, "a", "completed", "Step A"),
    progressMsg(5, "b", "completed", "Step B"),
    agentChunk(6, "ready"),
    promptResponseMsg(7, 1),
  ],
  "progress card updated across turn boundary": [
    userPromptMsg(1, 1, "first"),
    progressMsg(2, "a", "in_progress", "Step A", "g1"),
    promptResponseMsg(3, 1),
    userPromptMsg(4, 2, "second"),
    // late completion for g1 reaches back into the (now frozen) first turn
    progressMsg(5, "a", "completed", "Step A", "g1"),
    agentChunk(6, "ok"),
    promptResponseMsg(7, 2),
  ],
  "console and shell execute": [
    consoleMsg(1, "boot"),
    shellExecuteMsg(2, "sh1", "ls"),
    userPromptMsg(3, 1, "go"),
    consoleMsg(4, "running"),
    agentChunk(5, "out"),
    promptResponseMsg(6, 1),
  ],
};

const EQUIVALENCE_CASES = Object.entries(SCENARIOS).flatMap(([name, events]) =>
  ([true, false, null] as const).map((pending) => ({ name, events, pending })),
);

describe("createIncrementalConversationBuilder", () => {
  it.each(EQUIVALENCE_CASES)(
    "matches buildConversationItems at every prefix — $name (pending=$pending)",
    ({ events, pending }) => {
      assertEquivalentAcrossPrefixes(events, pending);
    },
  );

  // Stream every event (populating the persistent builder), then flip to idle
  // so the turn end takes the finalize-in-place path rather than a full rebuild.
  it.each(Object.entries(SCENARIOS))(
    "finalizes in place equivalently after streaming — %s",
    (_name, events) => {
      const inc = createIncrementalConversationBuilder();
      for (let k = 1; k <= events.length; k++) {
        inc.update(events.slice(0, k), true);
      }
      expect(normalize(inc.update(events, false))).toEqual(
        normalize(buildConversationItems(events, false)),
      );
    },
  );

  it("stays equivalent when streaming resumes after an in-place finalize", () => {
    const events = SCENARIOS["multi-turn with tools"];
    const inc = createIncrementalConversationBuilder();
    const firstTurnEnd = 7; // through promptResponseMsg(7, 1)

    for (let k = 1; k <= firstTurnEnd; k++)
      inc.update(events.slice(0, k), true);
    // Idle after turn 1 → finalize-in-place, which resets the builder.
    expect(normalize(inc.update(events.slice(0, firstTurnEnd), false))).toEqual(
      normalize(buildConversationItems(events.slice(0, firstTurnEnd), false)),
    );

    // Resume streaming turn 2 on the reset builder, then idle again.
    for (let k = firstTurnEnd + 1; k <= events.length; k++) {
      inc.update(events.slice(0, k), true);
    }
    expect(normalize(inc.update(events, false))).toEqual(
      normalize(buildConversationItems(events, false)),
    );
  });

  // The idle call arrives with trailing events the builder hasn't seen, so the
  // finalize-in-place catch-up loop must process them before finalizing.
  it("catches up trailing events that arrive with the idle flip", () => {
    const events = SCENARIOS["multi-turn with tools"];
    const inc = createIncrementalConversationBuilder();
    const streamedPrefix = 7; // through promptResponseMsg(7, 1)

    for (let k = 1; k <= streamedPrefix; k++) {
      inc.update(events.slice(0, k), true);
    }

    expect(normalize(inc.update(events, false))).toEqual(
      normalize(buildConversationItems(events, false)),
    );
  });

  // A full rebuild sorts by ts while the incremental builder processed arrival
  // order, so out-of-order events must reject finalize-in-place and fall back.
  it("falls back to a full rebuild on out-of-order timestamps at idle", () => {
    const events = [
      userPromptMsg(1, 1, "hello"),
      agentChunk(5, "later "),
      agentChunk(3, "earlier "),
      promptResponseMsg(6, 1),
    ];
    const inc = createIncrementalConversationBuilder();
    for (let k = 1; k <= events.length; k++) {
      inc.update(events.slice(0, k), true);
    }

    expect(normalize(inc.update(events, false))).toEqual(
      normalize(buildConversationItems(events, false)),
    );
  });

  it("keeps completed-turn item references stable while the active turn streams", () => {
    const inc = createIncrementalConversationBuilder();
    const base = [
      userPromptMsg(1, 1, "first"),
      agentChunk(2, "answer one"),
      promptResponseMsg(3, 1),
      userPromptMsg(4, 2, "second"),
      agentChunk(5, "A"),
    ];
    const r1 = inc.update(base, true);
    // [u1, a1, u2, a2]
    expect(r1.items).toHaveLength(4);

    const next = [...base, agentChunk(6, "B")];
    const r2 = inc.update(next, true);

    // Completed turn 1: identical object references — no re-render.
    expect(r2.items[0]).toBe(r1.items[0]);
    expect(r2.items[1]).toBe(r1.items[1]);
    // Active turn's static user message also stays referentially stable.
    expect(r2.items[2]).toBe(r1.items[2]);
    // Active streaming message is re-derived and its text has grown.
    expect(r2.items[3]).not.toBe(r1.items[3]);
    const active = r2.items[3];
    if (active.type !== "session_update" || !("content" in active.update)) {
      throw new Error("expected an agent message item");
    }
    expect((active.update.content as { text: string }).text).toBe("AB");
  });

  it("preserves a sent user message across idle -> streaming -> complete transitions", () => {
    const inc = createIncrementalConversationBuilder();
    const userMessages = (r: BuildResult) =>
      r.items.filter((i) => i.type === "user_message").map((i) => i.content);

    const turn1 = [
      userPromptMsg(1, 1, "first"),
      agentChunk(2, "answer one"),
      promptResponseMsg(3, 1),
    ];
    expect(userMessages(inc.update(turn1, false))).toEqual(["first"]);

    // User sends "second": the prompt echo is appended to events.
    const withPrompt = [...turn1, userPromptMsg(4, 2, "second")];
    // Renders that may straddle the pending flip — message must persist through all.
    expect(userMessages(inc.update(withPrompt, false))).toEqual([
      "first",
      "second",
    ]);
    expect(userMessages(inc.update(withPrompt, true))).toEqual([
      "first",
      "second",
    ]);

    const withChunk = [...withPrompt, agentChunk(5, "answer two")];
    expect(userMessages(inc.update(withChunk, true))).toEqual([
      "first",
      "second",
    ]);

    const done = [...withChunk, promptResponseMsg(6, 2)];
    expect(userMessages(inc.update(done, true))).toEqual(["first", "second"]);
    expect(userMessages(inc.update(done, false))).toEqual(["first", "second"]);
  });

  it("re-derives the active turn's context each call so live updates surface", () => {
    const inc = createIncrementalConversationBuilder();
    const base = [userPromptMsg(1, 1, "go"), toolCallMsg(2, "t1")];
    const r1 = inc.update(base, true);
    const next = [...base, toolUpdateMsg(3, "t1", { status: "completed" })];
    const r2 = inc.update(next, true);

    const tool1 = r1.items.find((i) => i.type === "session_update");
    const tool2 = r2.items.find((i) => i.type === "session_update");
    expect(tool1?.type).toBe("session_update");
    // Same logical row, fresh object — its memoized view re-renders.
    expect(tool2).not.toBe(tool1);
    if (tool2?.type === "session_update") {
      expect(tool2.turnContext.toolCalls.get("t1")?.status).toBe("completed");
    }
  });

  it("gives the active turn a fresh toolCalls Map identity each call so an in-place tool update re-renders", () => {
    // SessionUpdateView is memoized on `turnContext.toolCalls`, and tool_call_update
    // mutates the tool entry in place. If the Map reference is reused across calls
    // the memo bails and the completed status (and streamed output) stay hidden
    // until the turn ends. Guard that the Map identity changes every event.
    const inc = createIncrementalConversationBuilder();
    const base = [userPromptMsg(1, 1, "go"), toolCallMsg(2, "t1")];
    const r1 = inc.update(base, true);
    const next = [...base, toolUpdateMsg(3, "t1", { status: "completed" })];
    const r2 = inc.update(next, true);

    const ctx1 = r1.items.find((i) => i.type === "session_update");
    const ctx2 = r2.items.find((i) => i.type === "session_update");
    if (ctx1?.type !== "session_update" || ctx2?.type !== "session_update") {
      throw new Error("expected tool-call session_update rows");
    }
    expect(ctx2.turnContext.toolCalls).not.toBe(ctx1.turnContext.toolCalls);
    expect(ctx2.turnContext.childItems).not.toBe(ctx1.turnContext.childItems);
  });

  it("surfaces a running agent's child tool calls live, before the turn completes", () => {
    // A subagent appends child tool calls (parentToolCallId) while it runs. The
    // parent row is memoized on `turnContext.childItems`; without a fresh Map ref
    // the new children stay invisible until turn end. Guard that a child appended
    // mid-turn changes the childItems Map identity and is present.
    const inc = createIncrementalConversationBuilder();
    const base = [
      userPromptMsg(1, 1, "go"),
      toolCallMsg(2, "agent1", {
        _meta: { claudeCode: { toolName: "Agent" } },
      }),
    ];
    const r1 = inc.update(base, true);
    const next = [...base, childToolCallMsg(3, "child1", "agent1")];
    const r2 = inc.update(next, true);

    const row1 = r1.items.find((i) => i.type === "session_update");
    const row2 = r2.items.find((i) => i.type === "session_update");
    if (row1?.type !== "session_update" || row2?.type !== "session_update") {
      throw new Error("expected agent session_update rows");
    }
    // New child arrived mid-turn: fresh Map identity so the memoized parent re-renders.
    expect(row2.turnContext.childItems).not.toBe(row1.turnContext.childItems);
    expect(row2.turnContext.childItems.get("agent1")?.length).toBe(1);
  });

  it("groups canonical PostHog child metadata under its subagent", () => {
    const inc = createIncrementalConversationBuilder();
    const messages = [
      userPromptMsg(1, 1, "go"),
      toolCallMsg(2, "agent1", {
        _meta: { posthog: { toolName: "spawn_agent" } },
      }),
      updateMsg(3, {
        sessionUpdate: "tool_call",
        toolCallId: "child1",
        kind: "read",
        status: "pending",
        title: "child1",
        _meta: {
          posthog: {
            toolName: "subagent_activity",
            parentToolCallId: "agent1",
          },
        },
      }),
    ];

    const result = inc.update(messages, true);
    const row = result.items.find((item) => item.type === "session_update");
    if (row?.type !== "session_update") {
      throw new Error("expected agent session_update row");
    }
    expect(row.turnContext.childItems.get("agent1")?.length).toBe(1);
  });

  it("marks nested subagent thoughts complete when the turn finishes", () => {
    const inc = createIncrementalConversationBuilder();
    const messages = [
      userPromptMsg(1, 1, "go"),
      toolCallMsg(2, "agent1", {
        _meta: { posthog: { toolName: "spawn_agent" } },
      }),
      childThoughtChunk(3, "investigating", "agent1"),
      promptResponseMsg(4, 1),
    ];

    const result = inc.update(messages, false);
    const row = result.items.find((item) => item.type === "session_update");
    if (row?.type !== "session_update") {
      throw new Error("expected agent session_update row");
    }
    const thought = row.turnContext.childItems.get("agent1")?.[0];
    expect(thought).toMatchObject({
      type: "session_update",
      thoughtComplete: true,
      update: { sessionUpdate: "agent_thought_chunk" },
    });
  });
});
