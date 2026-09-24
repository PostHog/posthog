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

  it("keeps a chart-rendering tool call out of the chip so its UI app never hides behind it", () => {
    // The group collapses to "Thinking…" while a later call in the run is live,
    // hiding the already-rendered chart.
    const chartCall = toolItem("chart", { toolCallId: "chart" });
    chartCall.turnContext.toolCalls.set("chart", {
      toolCallId: "chart",
      title: "chart",
      kind: "execute",
      status: "completed",
      rawOutput: {
        _meta: { ui: { resourceUri: "ui://posthog/mock-app.html" } },
      },
    });

    const out = groupToolRuns([
      toolItem("before-1"),
      toolItem("before-2"),
      chartCall,
      toolItem("after-1"),
      toolItem("after-2"),
    ]);

    expect(out.map((row) => row.type)).toEqual([
      "tool_group",
      "session_update",
      "tool_group",
    ]);
    expect(out[1]).toMatchObject({ id: "chart" });
  });

  it("stands only the last chart-rendering call of a turn alone, folding earlier ones back into their run", () => {
    const turnContext = {
      toolCalls: new Map(),
      childItems: new Map(),
      turnCancelled: false,
      turnComplete: true,
    };
    const chart = (id: string) => {
      const item = toolItem(id, { toolCallId: id });
      item.turnContext = turnContext;
      turnContext.toolCalls.set(id, {
        toolCallId: id,
        title: id,
        kind: "execute",
        status: "completed",
        rawOutput: {
          _meta: { ui: { resourceUri: "ui://posthog/mock-app.html" } },
        },
      });
      return item;
    };
    const inTurn = (id: string) => {
      const item = toolItem(id);
      item.turnContext = turnContext;
      return item;
    };

    const out = groupToolRuns([
      inTurn("before-1"),
      inTurn("before-2"),
      chart("chart-1"),
      inTurn("between-1"),
      inTurn("between-2"),
      chart("chart-2"),
      inTurn("after-1"),
      inTurn("after-2"),
    ]);

    expect(out.map((row) => row.type)).toEqual([
      "tool_group",
      "session_update",
      "tool_group",
    ]);
    expect(out[1]).toMatchObject({ id: "chart-2" });
    expect(out[0]).toMatchObject({
      items: expect.arrayContaining([
        expect.objectContaining({ id: "chart-1" }),
      ]),
    });
  });

  it("holds every chart-rendering call inside its group until the turn completes", () => {
    const turnContext = {
      toolCalls: new Map(),
      childItems: new Map(),
      turnCancelled: false,
      turnComplete: false,
    };
    const chart = (id: string) => {
      const item = toolItem(id, { toolCallId: id });
      item.turnContext = turnContext;
      turnContext.toolCalls.set(id, {
        toolCallId: id,
        title: id,
        kind: "execute",
        status: "completed",
        rawOutput: {
          _meta: { ui: { resourceUri: "ui://posthog/mock-app.html" } },
        },
      });
      return item;
    };
    const inTurn = (id: string) => {
      const item = toolItem(id);
      item.turnContext = turnContext;
      return item;
    };

    const out = groupToolRuns([inTurn("before"), chart("chart-1")]);

    expect(out.map((row) => row.type)).toEqual(["tool_group"]);
  });

  it("stands a chart alone once its turn errors out, even without turnComplete", () => {
    const turnContext = {
      toolCalls: new Map(),
      childItems: new Map(),
      turnCancelled: false,
      turnComplete: false,
    };
    const chartCall = toolItem("chart-1", { toolCallId: "chart-1" });
    chartCall.turnContext = turnContext;
    turnContext.toolCalls.set("chart-1", {
      toolCallId: "chart-1",
      title: "chart-1",
      kind: "execute",
      status: "completed",
      rawOutput: {
        _meta: { ui: { resourceUri: "ui://posthog/mock-app.html" } },
      },
    });
    const inTurn = (id: string) => {
      const item = toolItem(id);
      item.turnContext = turnContext;
      return item;
    };
    const errorItem: SessionUpdateItem = {
      type: "session_update",
      id: "error",
      update: { sessionUpdate: "error", errorType: "runtime", message: "boom" },
      turnContext,
    };

    const out = groupToolRuns([inTurn("before"), chartCall, errorItem]);

    expect(out.map((row) => row.type)).toEqual([
      "session_update",
      "session_update",
      "session_update",
    ]);
    expect(out[1]).toMatchObject({ id: "chart-1" });
  });

  it("keeps every chart grouped while an implicit turn is still growing", () => {
    // An implicit (promptless) turn is marked turnComplete the instant it opens, so it
    // must not be trusted as a "done" signal on its own while nothing has superseded it.
    const turnContext = {
      toolCalls: new Map(),
      childItems: new Map(),
      turnCancelled: false,
      turnComplete: true,
      isImplicit: true,
    };
    const chart = (id: string) => {
      const item = toolItem(id, { toolCallId: id });
      item.turnContext = turnContext;
      turnContext.toolCalls.set(id, {
        toolCallId: id,
        title: id,
        kind: "execute",
        status: "completed",
        rawOutput: {
          _meta: { ui: { resourceUri: "ui://posthog/mock-app.html" } },
        },
      });
      return item;
    };

    const out = groupToolRuns([chart("chart-1"), chart("chart-2")]);

    expect(out.map((row) => row.type)).toEqual(["tool_group"]);
  });

  it("stands the last chart alone once a later turn supersedes the implicit one", () => {
    const turnContext = {
      toolCalls: new Map(),
      childItems: new Map(),
      turnCancelled: false,
      turnComplete: true,
      isImplicit: true,
    };
    const chart = (id: string) => {
      const item = toolItem(id, { toolCallId: id });
      item.turnContext = turnContext;
      turnContext.toolCalls.set(id, {
        toolCallId: id,
        title: id,
        kind: "execute",
        status: "completed",
        rawOutput: {
          _meta: { ui: { resourceUri: "ui://posthog/mock-app.html" } },
        },
      });
      return item;
    };

    const out = groupToolRuns([
      chart("chart-1"),
      chart("chart-2"),
      toolItem("next-turn"),
    ]);

    expect(out.map((row) => row.type)).toEqual([
      "session_update",
      "session_update",
      "session_update",
    ]);
    expect(out[1]).toMatchObject({ id: "chart-2" });
  });

  it("still groups an MCP tool call whose result has no UI app", () => {
    const execCall = toolItem("exec", {
      toolCallId: "exec",
      _meta: posthogToolMeta({
        toolName: "mcp__posthog__exec",
        mcp: { server: "posthog", tool: "exec" },
      }),
    });
    execCall.turnContext.toolCalls.set("exec", {
      toolCallId: "exec",
      title: "exec",
      kind: "execute",
      status: "completed",
      rawOutput: { content: [{ type: "text", text: "no chart here" }] },
    });

    const out = groupToolRuns([
      toolItem("before"),
      execCall,
      toolItem("after"),
    ]);

    expect(out.map((row) => row.type)).toEqual(["tool_group"]);
  });
});
