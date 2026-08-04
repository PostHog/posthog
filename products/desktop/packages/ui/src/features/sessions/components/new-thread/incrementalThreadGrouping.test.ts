import type {
  ConversationItem,
  TurnContext,
} from "@posthog/ui/features/sessions/components/buildConversationItems";
import {
  buildThreadGroups,
  type ThreadGrouping,
} from "@posthog/ui/features/sessions/components/new-thread/buildThreadGroups";
import { createIncrementalThreadGrouper } from "@posthog/ui/features/sessions/components/new-thread/incrementalThreadGrouping";
import { describe, expect, it } from "vitest";

const completeContext: TurnContext = {
  toolCalls: new Map(),
  childItems: new Map(),
  turnCancelled: false,
  turnComplete: true,
};

const activeContext: TurnContext = {
  toolCalls: new Map(),
  childItems: new Map(),
  turnCancelled: false,
  turnComplete: false,
};

function userMessage(id: string): ConversationItem {
  return {
    type: "user_message",
    id,
    content: id,
    timestamp: 1,
  };
}

function toolItem(
  id: string,
  turnContext: TurnContext = activeContext,
): ConversationItem {
  return {
    type: "session_update",
    id,
    turnContext,
    update: {
      sessionUpdate: "tool_call",
      toolCallId: id,
      kind: "read",
      title: "Read",
      status: turnContext.turnComplete ? "completed" : "in_progress",
    },
  };
}

function agentMessage(id: string): ConversationItem {
  return {
    type: "session_update",
    id,
    turnContext: activeContext,
    update: {
      sessionUpdate: "agent_message_chunk",
      content: { type: "text", text: "hello" },
    },
  };
}

function expectGroupingEquivalent(
  actual: ThreadGrouping,
  expected: ThreadGrouping,
) {
  expect(actual.rows).toEqual(expected.rows);
  expect(actual.keepMounted).toEqual(expected.keepMounted);
  expect([...actual.idToRowIndex.entries()]).toEqual([
    ...expected.idToRowIndex.entries(),
  ]);
}

describe("createIncrementalThreadGrouper", () => {
  it("matches a full regroup when appending to the active tool group", () => {
    const grouper = createIncrementalThreadGrouper();
    const overrides = {};
    const items = [
      userMessage("u1"),
      toolItem("t1", completeContext),
      userMessage("u2"),
      toolItem("t2"),
    ];

    grouper.update(items, "partial", overrides);

    const next = [...items, toolItem("t3")];
    expectGroupingEquivalent(
      grouper.update(next, "partial", overrides),
      buildThreadGroups(next, "partial", overrides),
    );
  });

  it("reuses the grouped prefix when appending a standalone row", () => {
    const grouper = createIncrementalThreadGrouper();
    const overrides = {};
    const items = [userMessage("u1"), toolItem("t1", completeContext)];
    const first = grouper.update(items, "partial", overrides);

    const next = [...items, agentMessage("m1")];
    const second = grouper.update(next, "partial", overrides);

    expectGroupingEquivalent(
      second,
      buildThreadGroups(next, "partial", overrides),
    );
    expect(second.rows[0]).toBe(first.rows[0]);
  });

  it("matches a full regroup when a streamed tool extends a completed group", () => {
    const grouper = createIncrementalThreadGrouper();
    const overrides = {};
    // A completed turn ending on a tool call, then a new turn's tool call with
    // no message between them: buildThreadGroups folds all three into one group
    // (groups break on item type, not turn completion), so the cut must not
    // split them.
    const items = [
      toolItem("c1", completeContext),
      toolItem("c2", completeContext),
    ];
    grouper.update(items, "partial", overrides);

    const next = [...items, toolItem("a1", activeContext)];
    expectGroupingEquivalent(
      grouper.update(next, "partial", overrides),
      buildThreadGroups(next, "partial", overrides),
    );
  });

  it("matches a full regroup after a reset-triggering replacement", () => {
    const grouper = createIncrementalThreadGrouper();
    const overrides = {};
    grouper.update(
      [userMessage("u1"), toolItem("t1", completeContext)],
      "partial",
      overrides,
    );

    // Same length, entirely new items — breaks the append invariant and forces
    // a full rebuild.
    const replaced = [userMessage("x1"), toolItem("y1", completeContext)];
    expectGroupingEquivalent(
      grouper.update(replaced, "partial", overrides),
      buildThreadGroups(replaced, "partial", overrides),
    );
  });

  it("does not mutate a previously returned grouping", () => {
    const grouper = createIncrementalThreadGrouper();
    const overrides = {};
    const items = [userMessage("u1"), toolItem("t1", completeContext)];
    const first = grouper.update(items, "partial", overrides);
    const firstEntries = [...first.idToRowIndex.entries()];

    grouper.update([...items, agentMessage("m1")], "partial", overrides);

    expect([...first.idToRowIndex.entries()]).toEqual(firstEntries);
  });
});
