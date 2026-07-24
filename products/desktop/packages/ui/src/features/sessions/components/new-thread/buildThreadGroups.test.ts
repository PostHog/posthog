import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { describe, expect, it } from "vitest";
import { buildThreadGroups, isGroupableItem } from "./buildThreadGroups";

function turnContext() {
  return {
    toolCalls: new Map(),
    childItems: new Map(),
    turnCancelled: false,
    turnComplete: true,
  };
}

function toolCallItem(
  id: string,
  meta: unknown,
  overrides?: Record<string, unknown>,
): ConversationItem {
  return {
    type: "session_update",
    id,
    update: {
      sessionUpdate: "tool_call",
      toolCallId: id,
      title: `tool ${id}`,
      kind: "other",
      status: "completed",
      _meta: meta,
      ...overrides,
    },
    turnContext: turnContext(),
  } as unknown as ConversationItem;
}

describe("buildThreadGroups MCP detection", () => {
  it("keeps a tool call with only the posthog meta channel standalone (codex adapters)", () => {
    const mcpItem = toolCallItem("t1", {
      posthog: {
        toolName: "mcp__posthog__exec",
        mcp: { server: "posthog", tool: "exec" },
      },
    });

    expect(isGroupableItem(mcpItem)).toBe(false);

    const grouping = buildThreadGroups([mcpItem], "all", {});
    expect(grouping.rows).toHaveLength(1);
    expect(grouping.rows[0].kind).toBe("item");
    expect(grouping.keepMounted).toEqual([0]);
  });

  it("keeps a tool call with the legacy claudeCode mcp__ name standalone", () => {
    const legacyItem = toolCallItem("t1", {
      claudeCode: { toolName: "mcp__github__search" },
    });

    expect(isGroupableItem(legacyItem)).toBe(false);
    const grouping = buildThreadGroups([legacyItem], "all", {});
    expect(grouping.keepMounted).toEqual([0]);
  });

  it("folds non-MCP tool calls into a collapsed group", () => {
    const plain = toolCallItem("t1", {
      posthog: { toolName: "Bash" },
    });
    const alsoPlain = toolCallItem("t2", undefined, { kind: "read" });

    const grouping = buildThreadGroups([plain, alsoPlain], "all", {});
    expect(grouping.rows).toHaveLength(1);
    expect(grouping.rows[0].kind).toBe("tool_group");
    expect(grouping.keepMounted).toEqual([]);
    // Both folded items still map to the group's row for find-in-thread.
    expect(grouping.idToRowIndex.get("t1")).toBe(0);
    expect(grouping.idToRowIndex.get("t2")).toBe(0);
  });

  it("counts only spawned agents as subagents", () => {
    const items = [
      toolCallItem("spawn-1", {
        posthog: { toolName: "spawn_agent" },
      }),
      toolCallItem("wait-1", {
        posthog: { toolName: "wait_agent" },
      }),
      toolCallItem("close-1", {
        posthog: { toolName: "close_agent" },
      }),
    ];

    const grouping = buildThreadGroups(items, "all", {});
    const row = grouping.rows[0];
    expect(row.kind).toBe("tool_group");
    if (row.kind !== "tool_group") return;
    expect(row.summary.counts.subagents).toBe(1);
    expect(row.summary.counts.other).toBe(2);
    expect(row.summary.doneLabel).toBe("1 subagent, 2 tool calls");
  });
});
