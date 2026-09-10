import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import type { ThreadRow } from "@posthog/ui/features/sessions/components/new-thread/buildThreadGroups";
import { describe, expect, it } from "vitest";
import { groupRowsIntoTurns } from "./groupConversationTurns";

function row(item: ConversationItem): ThreadRow {
  return { kind: "item", id: item.id, item };
}

function userMessage(id: string): ConversationItem {
  return { type: "user_message", id, content: id, timestamp: 0 };
}

function cancelled(id: string): ConversationItem {
  return { type: "turn_cancelled", id } as ConversationItem;
}

function userAction(
  id: string,
  type: "git_action" | "skill_button_action",
): ConversationItem {
  return { type, id } as ConversationItem;
}

describe("groupRowsIntoTurns", () => {
  it("keeps each prompt and its response in one virtual row", () => {
    const result = groupRowsIntoTurns([
      row(userMessage("user-1")),
      row(cancelled("reply-1")),
      row(userMessage("user-2")),
      row(cancelled("reply-2")),
    ]);

    expect(
      result.turns.map((turn) => turn.rows.map((item) => item.id)),
    ).toEqual([
      ["user-1", "reply-1"],
      ["user-2", "reply-2"],
    ]);
  });

  it("maps source rows to their virtual turn", () => {
    const result = groupRowsIntoTurns([
      row(userMessage("user-1")),
      row(cancelled("reply-1")),
      row(userMessage("user-2")),
    ]);

    expect(result.rowToTurnIndex).toEqual([0, 0, 1]);
  });

  it.each(["git_action", "skill_button_action"] as const)(
    "starts a turn for %s",
    (type) => {
      const result = groupRowsIntoTurns([
        row(userMessage("user-1")),
        row(cancelled("reply-1")),
        row(userAction("action-1", type)),
        row(cancelled("reply-2")),
      ]);

      expect(
        result.turns.map((turn) => turn.rows.map((item) => item.id)),
      ).toEqual([
        ["user-1", "reply-1"],
        ["action-1", "reply-2"],
      ]);
    },
  );
});
