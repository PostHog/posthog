import { posthogToolMeta } from "@posthog/shared";
import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { describe, expect, it } from "vitest";
import { groupToolRuns } from "./ChatThread";

type SessionUpdateItem = Extract<ConversationItem, { type: "session_update" }>;

function toolItem(
  id: string,
  update: Record<string, unknown> = {},
): SessionUpdateItem {
  return {
    type: "session_update",
    id,
    update: {
      sessionUpdate: "tool_call",
      toolCallId: id,
      title: id,
      kind: "execute",
      status: "completed",
      ...update,
    },
    turnContext: {
      toolCalls: new Map(),
      childItems: new Map(),
      turnCancelled: false,
      turnComplete: true,
    },
  } as SessionUpdateItem;
}

const planItem = (id: string, update: Record<string, unknown> = {}) =>
  toolItem(id, { kind: "switch_mode", title: "Ready to code?", ...update });

describe("groupToolRuns", () => {
  it("collapses a plain run of tools into one chip", () => {
    const out = groupToolRuns([toolItem("t1"), toolItem("t2")]);
    expect(out.map((r) => r.type)).toEqual(["tool_group"]);
  });

  it("keeps a plan approval out of the chip so the plan card renders", () => {
    // The reproducing shape: the agent edits the plan file, then calls
    // ExitPlanMode — grouped, the plan the user must approve is invisible.
    const out = groupToolRuns([toolItem("edit"), planItem("plan")]);
    expect(out.map((r) => r.type)).toEqual([
      "session_update",
      "session_update",
    ]);
    expect(out[1]).toMatchObject({ id: "plan" });
  });

  it("breaks a longer run around the plan", () => {
    const out = groupToolRuns([
      toolItem("t1"),
      toolItem("t2"),
      planItem("plan"),
      toolItem("t3"),
    ]);
    expect(out.map((r) => r.type)).toEqual([
      "tool_group",
      "session_update",
      "session_update",
    ]);
    expect(out[1]).toMatchObject({ id: "plan" });
  });

  it("exempts a plan identified only by its agent tool name", () => {
    const out = groupToolRuns([
      toolItem("edit"),
      planItem("plan", {
        kind: "other",
        _meta: { claudeCode: { toolName: "ExitPlanMode" } },
      }),
    ]);
    expect(out.map((r) => r.type)).toEqual([
      "session_update",
      "session_update",
    ]);
  });

  it.each([
    ["Claude initial call", true],
    ["Pi resolved call", false],
  ])("keeps action buttons visible from the %s metadata", (_, initial) => {
    const action = toolItem("action", {
      ...(initial
        ? {
            _meta: {
              claudeCode: {
                toolName: "mcp__posthog-code-tools__show_actions",
              },
            },
          }
        : {}),
    });
    if (!initial) {
      action.turnContext.toolCalls.set("action", {
        toolCallId: "action",
        title: "action",
        kind: "execute",
        status: "completed",
        _meta: posthogToolMeta({
          toolName: "mcp__posthog-code-tools__show_actions",
          mcp: { server: "posthog-code-tools", tool: "show_actions" },
        }),
      });
    }

    const out = groupToolRuns([
      toolItem("before-1"),
      toolItem("before-2"),
      action,
      toolItem("after-1"),
      toolItem("after-2"),
    ]);

    expect(out.map((row) => row.type)).toEqual([
      "tool_group",
      "session_update",
      "tool_group",
    ]);
    expect(out[1]).toMatchObject({ id: "action" });
  });
});
