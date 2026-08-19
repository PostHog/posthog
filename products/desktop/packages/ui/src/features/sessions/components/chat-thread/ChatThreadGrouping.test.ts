import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { createIncrementalChatRowGrouper } from "@posthog/ui/features/sessions/components/chat-thread/chatRowGrouping";
import type { TurnRow } from "@posthog/ui/features/sessions/components/chat-thread/threadVirtualization";
import { isUserInitiatedConversationItem } from "@posthog/ui/features/sessions/components/isUserInitiatedConversationItem";
import { describe, expect, it } from "vitest";

function userMessage(id: string): ConversationItem {
  return { type: "user_message", id, content: id, timestamp: 1 };
}

function agentMessage(id: string, text = id): ConversationItem {
  return {
    type: "session_update",
    id,
    turnContext: {
      toolCalls: new Map(),
      childItems: new Map(),
      turnCancelled: false,
      turnComplete: false,
    },
    update: {
      sessionUpdate: "agent_message_chunk",
      content: { type: "text", text },
    },
  };
}

function groupRows(items: ConversationItem[]): TurnRow[] {
  const rows: TurnRow[] = [];
  let agentItems: ConversationItem[] = [];
  const flush = () => {
    if (agentItems.length > 0) {
      rows.push({
        type: "agent_turn",
        id: agentItems[0].id,
        items: agentItems,
      });
      agentItems = [];
    }
  };
  for (const item of items) {
    if (isUserInitiatedConversationItem(item)) {
      flush();
      rows.push(item);
    } else {
      agentItems.push(item);
    }
  }
  flush();
  return rows;
}

describe("createIncrementalChatRowGrouper", () => {
  it("reuses completed turns while rebuilding the active turn", () => {
    const grouper = createIncrementalChatRowGrouper(groupRows);
    const firstItems = [userMessage("u1"), agentMessage("a1")];
    const first = grouper.update(firstItems);
    const secondItems = [...firstItems, userMessage("u2"), agentMessage("a2")];
    const second = grouper.update(secondItems, 2);
    const third = grouper.update([...secondItems, agentMessage("a3")], 2);

    expect(second[0]).toBe(first[0]);
    expect(second[1]).toBe(first[1]);
    expect(third[0]).toBe(second[0]);
    expect(third[1]).toBe(second[1]);
    expect(third.at(-1)).toMatchObject({
      type: "agent_turn",
      items: [{ id: "a2" }, { id: "a3" }],
    });
  });

  it("fully rebuilds after a non-append replacement", () => {
    const grouper = createIncrementalChatRowGrouper(groupRows);
    grouper.update([userMessage("u1"), agentMessage("a1")]);

    expect(
      grouper.update([userMessage("x1"), agentMessage("x2")]),
    ).toMatchObject([
      { id: "x1" },
      { type: "agent_turn", items: [{ id: "x2" }] },
    ]);
  });

  it("rebuilds same-id rows when the stable prefix is reset", () => {
    const grouper = createIncrementalChatRowGrouper(groupRows);
    grouper.update([
      userMessage("u1"),
      agentMessage("a1", "old response"),
      userMessage("u2"),
      agentMessage("a2"),
    ]);

    const replacement = agentMessage("a1", "replacement response");
    const rows = grouper.update(
      [userMessage("u1"), replacement, userMessage("u2"), agentMessage("a2")],
      0,
    );
    const firstAgentTurn = rows[1];

    if (firstAgentTurn.type !== "agent_turn") {
      throw new Error("expected an agent turn");
    }
    expect(firstAgentTurn.items[0]).toBe(replacement);
  });

  it("rebuilds when a row inside the retained prefix is replaced in place", () => {
    // The conversation builder swaps row objects at arbitrary indices (a status
    // completing, a shell result arriving) — including inside turns the grouper
    // already cached. The cached rows must not survive such a replacement.
    const grouper = createIncrementalChatRowGrouper(groupRows);
    const u1 = userMessage("u1");
    const status = agentMessage("s1");
    const u2 = userMessage("u2");
    grouper.update([u1, status, u2]);

    const replaced = { ...status };
    const rows = grouper.update([u1, replaced, u2, agentMessage("a2")]);

    const turn = rows[1];
    if (turn.type !== "agent_turn") throw new Error("expected an agent turn");
    expect(turn.items[0]).toBe(replaced);
  });

  it("replaces an optimistic boundary whose confirmed item has a new id", () => {
    const grouper = createIncrementalChatRowGrouper(groupRows);
    const prefix = [userMessage("u1"), agentMessage("a1")];
    grouper.update([...prefix, userMessage("optimistic-u2")], 2);

    expect(
      grouper.update(
        [...prefix, userMessage("confirmed-u2"), agentMessage("a2")],
        2,
      ),
    ).toMatchObject([
      { id: "u1" },
      { type: "agent_turn", items: [{ id: "a1" }] },
      { id: "confirmed-u2" },
      { type: "agent_turn", items: [{ id: "a2" }] },
    ]);
  });

  it("does not inspect the completed prefix on a streamed append", () => {
    const grouper = createIncrementalChatRowGrouper(groupRows);
    const items = [
      userMessage("u1"),
      agentMessage("a1"),
      userMessage("u2"),
      agentMessage("a2"),
    ];
    grouper.update(items, 2);
    const inspected = new Set<number>();
    const next = new Proxy([...items, agentMessage("a3")], {
      get(target, property, receiver) {
        if (typeof property === "string" && /^\d+$/.test(property)) {
          inspected.add(Number(property));
        }
        return Reflect.get(target, property, receiver);
      },
    });

    grouper.update(next, 2);

    expect(inspected.has(0)).toBe(false);
  });
});
