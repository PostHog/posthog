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

/** Put the settled call (the one carrying output) in the turn's map, as a
 *  tool_call_update does. */
function resolveToolCall(item: ConversationItem, resolved: unknown): void {
  if (item.type !== "session_update") return;
  item.turnContext.toolCalls.set(
    (resolved as { toolCallId: string }).toolCallId,
    resolved as never,
  );
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

    const grouping = buildThreadGroups([mcpItem], {});
    expect(grouping.rows).toHaveLength(1);
    expect(grouping.rows[0].kind).toBe("item");
    expect(grouping.keepMounted).toEqual([0]);
  });

  it("keeps a tool call with the legacy claudeCode mcp__ name standalone", () => {
    const legacyItem = toolCallItem("t1", {
      claudeCode: { toolName: "mcp__github__search" },
    });

    expect(isGroupableItem(legacyItem)).toBe(false);
    const grouping = buildThreadGroups([legacyItem], {});
    expect(grouping.keepMounted).toEqual([0]);
  });

  it("folds non-MCP tool calls into a collapsed group", () => {
    const plain = toolCallItem("t1", {
      posthog: { toolName: "Bash" },
    });
    const alsoPlain = toolCallItem("t2", undefined, { kind: "read" });

    const grouping = buildThreadGroups([plain, alsoPlain], {});
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

    const grouping = buildThreadGroups(items, {});
    const row = grouping.rows[0];
    expect(row.kind).toBe("tool_group");
    if (row.kind !== "tool_group") return;
    expect(row.summary.counts.subagents).toBe(1);
    expect(row.summary.counts.other).toBe(2);
    expect(row.summary.doneLabel).toBe("1 subagent, 2 tool calls");
  });
});

describe("buildThreadGroups artifact detection", () => {
  // A PR's url arrives on the tool_call_update, which lands in the turn's tool
  // call map rather than on the item grouping walks. Reading only the item folds
  // the call into a collapsed group and hides the card the run just earned.
  it("keeps a pull request the run opened as its own row", () => {
    const bash = toolCallItem(
      "bash",
      { posthog: { toolName: "Bash" } },
      { kind: "execute" },
    );
    const create = toolCallItem(
      "create-pr",
      { posthog: { toolName: "Bash" } },
      { kind: "execute", rawInput: { command: "gh pr create --fill" } },
    );
    resolveToolCall(create, {
      toolCallId: "create-pr",
      kind: "execute",
      status: "completed",
      rawInput: { command: "gh pr create --fill" },
      content: [
        {
          type: "content",
          content: {
            type: "text",
            text: "https://github.com/PostHog/posthog/pull/82584",
          },
        },
      ],
    });

    expect(isGroupableItem(create)).toBe(false);

    const grouping = buildThreadGroups([bash, create], {});
    expect(grouping.rows.map((r) => r.kind)).toEqual(["tool_group", "item"]);
    expect(grouping.idToRowIndex.get("create-pr")).toBe(1);
  });
});

describe("buildThreadGroups plan detection", () => {
  // The plan tool call is emitted from the model's raw input, and its plan text
  // and switch_mode kind are backfilled by the permission handler. Grouping by
  // kind alone folds an ExitPlanMode call into the collapsed tool group before
  // its kind resolves — burying the plan the user is meant to read. Matching by
  // tool name keeps it as its own row regardless of when the kind arrives.
  it.each([
    ["switch_mode kind", { kind: "switch_mode" }, undefined],
    [
      "ExitPlanMode name, kind not yet resolved",
      { kind: "other" },
      { claudeCode: { toolName: "ExitPlanMode" } },
    ],
  ])(
    "keeps a plan tool call (%s) as its own row, not folded into a group",
    (_label, overrides, meta) => {
      const write = toolCallItem(
        "write",
        { claudeCode: { toolName: "Write" } },
        { kind: "edit" },
      );
      const plan = toolCallItem("plan", meta, overrides);

      expect(isGroupableItem(plan)).toBe(false);

      const grouping = buildThreadGroups([write, plan], {});
      expect(grouping.rows.map((r) => r.kind)).toEqual(["tool_group", "item"]);
      expect(grouping.idToRowIndex.get("plan")).toBe(1);
    },
  );
});
