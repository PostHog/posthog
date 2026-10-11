import type {
  ConversationItem,
  TurnContext,
} from "@posthog/ui/features/sessions/components/buildConversationItems";
import { describe, expect, it } from "vitest";
import { collectSessionSubagents, findItemRow } from "./sessionSubagents";

type SessionUpdateItem = Extract<ConversationItem, { type: "session_update" }>;

function turn(overrides: Partial<TurnContext> = {}): TurnContext {
  return {
    toolCalls: new Map(),
    childItems: new Map(),
    turnCancelled: false,
    turnComplete: false,
    ...overrides,
  };
}

function toolItem(
  id: string,
  update: Record<string, unknown>,
  turnContext: TurnContext = turn(),
): SessionUpdateItem {
  return {
    type: "session_update",
    id,
    update: {
      sessionUpdate: "tool_call",
      toolCallId: id,
      kind: "other",
      status: "in_progress",
      ...update,
    },
    turnContext,
  } as SessionUpdateItem;
}

describe("collectSessionSubagents", () => {
  it("lists each run of a parallel Pi subagent call with its live tool and result", () => {
    const item = toolItem("pi", {
      title: "subagent",
      details: {
        mode: "parallel",
        results: [
          {
            runId: "a",
            agent: "explorer",
            task: "Find the routes",
            description: "Find the routes",
            state: "running",
            toolCalls: [
              {
                id: "c1",
                name: "grep",
                title: "grep routes",
                kind: "search",
                status: "in_progress",
                rawInput: {},
              },
            ],
          },
          {
            runId: "b",
            agent: "reviewer",
            task: "Review the diff",
            state: "completed",
            resultText: "No issues\nfound",
          },
        ],
      },
    });

    expect(collectSessionSubagents([item])).toMatchObject([
      {
        itemId: "pi",
        label: "Find the routes",
        status: "in_progress",
        currentTool: "grep routes",
      },
      {
        itemId: "pi",
        label: "Review the diff",
        status: "completed",
        result: "No issues found",
      },
    ]);
  });

  it("reads a Task call's current tool from its child items, and its result once done", () => {
    const child = toolItem("child", { title: "Read src/app.ts" });
    const running = toolItem(
      "task",
      { title: "Explore the app", _meta: { claudeCode: { toolName: "Task" } } },
      turn({ childItems: new Map([["task", [child]]]) }),
    );
    expect(collectSessionSubagents([running])).toMatchObject([
      {
        label: "Explore the app",
        status: "in_progress",
        currentTool: "Read src/app.ts",
      },
    ]);

    const doneTurn = turn({ turnComplete: true });
    const done = toolItem(
      "task",
      { title: "Explore the app", _meta: { claudeCode: { toolName: "Task" } } },
      doneTurn,
    );
    doneTurn.toolCalls.set("task", {
      toolCallId: "task",
      title: "Explore the app",
      status: "completed",
      _meta: { claudeCode: { toolName: "Task" } },
      content: [{ type: "content", content: { type: "text", text: "Done" } }],
    } as never);
    expect(collectSessionSubagents([done])).toMatchObject([
      { status: "completed", result: "Done" },
    ]);
  });

  it("marks a subagent that never finished as stopped once its turn ends", () => {
    const item = toolItem(
      "task",
      { title: "Explore", _meta: { claudeCode: { toolName: "Agent" } } },
      turn({ turnCancelled: true }),
    );
    expect(collectSessionSubagents([item])[0].status).toBe("pending");
  });

  it("ignores tool calls that are not subagents", () => {
    expect(
      collectSessionSubagents([
        toolItem("bash", { title: "ls", kind: "execute" }),
      ]),
    ).toEqual([]);
  });
});

describe("findItemRow", () => {
  it("resolves an item inside a tool group to its turn and its group", () => {
    const task = toolItem("task", { title: "Explore" });
    const other = toolItem("other", { title: "ls" });
    const rows = [
      {
        type: "agent_turn" as const,
        id: "turn-1",
        items: [
          { type: "tool_group" as const, id: "other", items: [other, task] },
        ],
      },
    ];
    expect(findItemRow(rows, "task")).toEqual({
      turnId: "turn-1",
      rowId: "other",
    });
    expect(findItemRow(rows, "missing")).toBeUndefined();
  });
});
