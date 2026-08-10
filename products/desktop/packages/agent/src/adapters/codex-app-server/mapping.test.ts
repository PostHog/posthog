import { describe, expect, it } from "vitest";
import {
  mapAppServerNotification,
  mapHistoryItem,
  parseUnifiedDiff,
} from "./mapping";
import { APP_SERVER_NOTIFICATIONS } from "./protocol";

describe("mapAppServerNotification", () => {
  it("maps an agent message delta to an ACP agent_message_chunk", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.AGENT_MESSAGE_DELTA,
      { itemId: "item_1", delta: "Hello" },
    );

    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "agent_message_chunk",
        content: { type: "text", text: "Hello" },
      },
    });
  });

  it.each([
    ["raw textDelta", APP_SERVER_NOTIFICATIONS.REASONING_TEXT_DELTA],
    ["summaryTextDelta", APP_SERVER_NOTIFICATIONS.REASONING_SUMMARY_TEXT_DELTA],
  ])("maps a reasoning %s to an ACP agent_thought_chunk", (_label, method) => {
    const result = mapAppServerNotification("s-1", method, {
      itemId: "item_1",
      delta: "thinking",
      contentIndex: 0,
    });

    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "agent_thought_chunk",
        content: { type: "text", text: "thinking" },
      },
    });
  });

  it("keeps plan deltas out of the agent transcript", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.PLAN_DELTA,
      { itemId: "p1", delta: "## Plan\n" },
    );

    expect(result).toBeNull();
  });

  it("returns null when the delta is missing or empty", () => {
    expect(
      mapAppServerNotification(
        "s-1",
        APP_SERVER_NOTIFICATIONS.AGENT_MESSAGE_DELTA,
        {},
      ),
    ).toBeNull();
    expect(
      mapAppServerNotification(
        "s-1",
        APP_SERVER_NOTIFICATIONS.AGENT_MESSAGE_DELTA,
        { itemId: "item_1", delta: "" },
      ),
    ).toBeNull();
  });

  it("maps a started command execution item to a tool_call", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.ITEM_STARTED,
      { item: { type: "commandExecution", id: "i1", command: "ls -la" } },
    );

    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "tool_call",
        toolCallId: "i1",
        title: "ls -la",
        kind: "execute",
        status: "in_progress",
      },
    });
  });

  it("maps a completed command execution item to a tool_call_update with output", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.ITEM_COMPLETED,
      {
        item: {
          type: "commandExecution",
          id: "i1",
          command: "ls",
          status: "completed",
          aggregatedOutput: "file.txt",
        },
      },
    );

    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "tool_call_update",
        toolCallId: "i1",
        status: "completed",
        content: [
          { type: "content", content: { type: "text", text: "file.txt" } },
        ],
      },
    });
  });

  it("maps a started webSearch item to a fetch tool_call titled by its query", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.ITEM_STARTED,
      { item: { type: "webSearch", id: "w1", query: "posthog hogql docs" } },
    );

    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "tool_call",
        toolCallId: "w1",
        title: "posthog hogql docs",
        kind: "fetch",
        status: "in_progress",
      },
    });

    const queryless = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.ITEM_STARTED,
      { item: { type: "webSearch", id: "w2" } },
    );
    expect(queryless?.update).toMatchObject({ title: "Web search" });
  });

  it("maps a declined completion to a failed tool_call_update", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.ITEM_COMPLETED,
      {
        item: {
          type: "commandExecution",
          id: "i2",
          command: "rm -rf build",
          status: "declined",
        },
      },
    );

    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "tool_call_update",
        toolCallId: "i2",
        status: "failed",
      },
    });
  });

  it("maps a started mcp tool call item, surfacing arguments as rawInput", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.ITEM_STARTED,
      {
        item: {
          type: "mcpToolCall",
          id: "m1",
          server: "posthog",
          tool: "execute-sql",
          arguments: { query: "SELECT 1" },
        },
      },
    );

    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "tool_call",
        toolCallId: "m1",
        title: "posthog/execute-sql",
        kind: "other",
        status: "in_progress",
        rawInput: { query: "SELECT 1" },
        _meta: {
          posthog: {
            toolName: "mcp__posthog__execute-sql",
            mcp: { server: "posthog", tool: "execute-sql" },
          },
        },
      },
    });
  });

  it("tags an mcp exec tool call with the structured posthog channel the renderer routes on", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.ITEM_STARTED,
      {
        item: {
          type: "mcpToolCall",
          id: "m2",
          server: "posthog",
          tool: "exec",
          arguments: { command: "call execute-sql {}" },
        },
      },
    );

    const meta = (result?.update as { _meta?: unknown })._meta as {
      posthog?: { toolName?: string; mcp?: { server: string; tool: string } };
    };
    expect(meta.posthog).toEqual({
      toolName: "mcp__posthog__exec",
      mcp: { server: "posthog", tool: "exec" },
    });
  });

  it("maps a spawned Codex agent to an explicit subagent tool call", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.ITEM_STARTED,
      {
        item: {
          type: "collabAgentToolCall",
          id: "spawn-1",
          tool: "spawnAgent",
          status: "inProgress",
          senderThreadId: "main-thread",
          receiverThreadIds: ["child-thread"],
          prompt: "Review the authentication changes\nFocus on security.",
          model: "gpt-5.5",
          reasoningEffort: "high",
        },
      },
    );

    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "tool_call",
        toolCallId: "spawn-1",
        title: "Review the authentication changes",
        kind: "other",
        status: "in_progress",
        rawInput: {
          prompt: "Review the authentication changes\nFocus on security.",
          receiverThreadIds: ["child-thread"],
          model: "gpt-5.5",
          reasoningEffort: "high",
        },
        _meta: { posthog: { toolName: "spawn_agent" } },
      },
    });
  });

  it("keeps a completed spawn tool call terminal while its subagent is running", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.ITEM_COMPLETED,
      {
        item: {
          type: "collabAgentToolCall",
          id: "spawn-1",
          tool: "spawnAgent",
          status: "completed",
          senderThreadId: "main-thread",
          receiverThreadIds: ["child-thread"],
          prompt: "Review the authentication changes",
          agentsStates: {
            "child-thread": { status: "running", message: null },
          },
        },
      },
    );

    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "tool_call_update",
        toolCallId: "spawn-1",
        status: "completed",
      },
    });
  });

  it("drops agent message items (their deltas already streamed)", () => {
    expect(
      mapAppServerNotification("s-1", APP_SERVER_NOTIFICATIONS.ITEM_COMPLETED, {
        item: { type: "agentMessage", id: "a1", text: "done" },
      }),
    ).toBeNull();
  });

  it("maps thread/tokenUsage/updated to a usage_update from the per-turn `last` (not cumulative `total`)", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.TOKEN_USAGE_UPDATED,
      {
        threadId: "t",
        turnId: "u",
        tokenUsage: {
          total: { totalTokens: 1500, inputTokens: 1000, outputTokens: 500 },
          last: {
            totalTokens: 600,
            inputTokens: 500,
            outputTokens: 100,
            cachedInputTokens: 0,
            reasoningOutputTokens: 0,
          },
          modelContextWindow: 200000,
        },
      },
    );
    expect(result).toEqual({
      sessionId: "s-1",
      update: { sessionUpdate: "usage_update", used: 600, size: 200000 },
    });
  });

  it("falls back to cumulative `total` when `last` is absent (pre-`last` build / turn 1)", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.TOKEN_USAGE_UPDATED,
      {
        threadId: "t",
        turnId: "u",
        tokenUsage: {
          total: { totalTokens: 1500, inputTokens: 1000, outputTokens: 500 },
          modelContextWindow: 200000,
        },
      },
    );
    expect(result).toEqual({
      sessionId: "s-1",
      update: { sessionUpdate: "usage_update", used: 1500, size: 200000 },
    });
  });

  it("maps turn/plan/updated to a plan update", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.TURN_PLAN_UPDATED,
      {
        threadId: "t",
        turnId: "u",
        plan: [
          { step: "Read files", status: "completed" },
          { step: "Edit", status: "inProgress" },
        ],
      },
    );
    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "plan",
        entries: [
          { content: "Read files", priority: "medium", status: "completed" },
          { content: "Edit", priority: "medium", status: "in_progress" },
        ],
      },
    });
  });

  it("maps a completed fileChange to a tool_call_update with diff content", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.ITEM_COMPLETED,
      {
        item: {
          type: "fileChange",
          id: "f1",
          status: "completed",
          changes: [{ path: "a.txt", diff: "@@ -1 +1 @@\n-old\n+new" }],
        },
      },
    );
    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "tool_call_update",
        toolCallId: "f1",
        status: "completed",
        content: [
          { type: "diff", path: "a.txt", oldText: "old", newText: "new" },
        ],
      },
    });
  });

  it("includes cwd as a follow-along location on a started command execution", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.ITEM_STARTED,
      {
        item: {
          type: "commandExecution",
          id: "c1",
          command: "pytest",
          cwd: "/repo",
        },
      },
    );
    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "tool_call",
        toolCallId: "c1",
        title: "pytest",
        kind: "execute",
        status: "in_progress",
        locations: [{ path: "/repo" }],
      },
    });
  });

  it("prefers command-action paths over cwd for read commands", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.ITEM_STARTED,
      {
        item: {
          type: "commandExecution",
          id: "c2",
          command: "cat foo.txt",
          cwd: "/repo",
          commandActions: [
            { type: "read", path: "/repo/foo.txt" },
            { type: "read", path: "/repo/foo.txt" },
          ],
        },
      },
    );
    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "tool_call",
        toolCallId: "c2",
        title: "cat foo.txt",
        kind: "read",
        status: "in_progress",
        locations: [{ path: "/repo/foo.txt" }],
      },
    });
  });

  it("titles a started fileChange with its path and exposes locations", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.ITEM_STARTED,
      {
        item: {
          type: "fileChange",
          id: "f2",
          changes: [{ path: "src/a.ts" }, { path: "src/b.ts" }],
        },
      },
    );
    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "tool_call",
        toolCallId: "f2",
        title: "src/a.ts (+1 more)",
        kind: "edit",
        status: "in_progress",
        locations: [{ path: "src/a.ts" }, { path: "src/b.ts" }],
      },
    });
  });

  it("streams command output deltas as in-progress tool_call_update text", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.COMMAND_OUTPUT_DELTA,
      { threadId: "t", turnId: "u", itemId: "c1", delta: "line 1\n" },
    );
    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "tool_call_update",
        toolCallId: "c1",
        status: "in_progress",
        content: [
          { type: "content", content: { type: "text", text: "line 1\n" } },
        ],
      },
    });
  });

  it("echoes terminal interaction stdin into the tool call output", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.TERMINAL_INTERACTION,
      {
        threadId: "t",
        turnId: "u",
        itemId: "c1",
        processId: "p1",
        stdin: "y\n",
      },
    );
    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "tool_call_update",
        toolCallId: "c1",
        status: "in_progress",
        content: [{ type: "content", content: { type: "text", text: "y\n" } }],
      },
    });
  });

  it("returns null for an output delta missing itemId or delta", () => {
    expect(
      mapAppServerNotification(
        "s-1",
        APP_SERVER_NOTIFICATIONS.COMMAND_OUTPUT_DELTA,
        { itemId: "c1", delta: "" },
      ),
    ).toBeNull();
    expect(
      mapAppServerNotification(
        "s-1",
        APP_SERVER_NOTIFICATIONS.COMMAND_OUTPUT_DELTA,
        { delta: "x" },
      ),
    ).toBeNull();
  });

  it("streams fileChange patch updates as in-progress diff content", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.FILE_CHANGE_PATCH_UPDATED,
      {
        threadId: "t",
        turnId: "u",
        itemId: "f1",
        changes: [
          {
            path: "a.txt",
            kind: { type: "update" },
            diff: "@@ -1 +1 @@\n-x\n+y",
          },
        ],
      },
    );
    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "tool_call_update",
        toolCallId: "f1",
        status: "in_progress",
        content: [{ type: "diff", path: "a.txt", oldText: "x", newText: "y" }],
      },
    });
  });

  it("returns null for the turn completion notification", () => {
    expect(
      mapAppServerNotification("s-1", APP_SERVER_NOTIFICATIONS.TURN_COMPLETED, {
        turn: { status: "completed" },
      }),
    ).toBeNull();
  });
});

describe("mapHistoryItem", () => {
  it("replays a userMessage's text inputs as user_message_chunks", () => {
    expect(
      mapHistoryItem("s-1", {
        type: "userMessage",
        id: "u1",
        content: [
          { type: "text", text: "hello", text_elements: [] },
          { type: "image", url: "data:image/png;base64,AAAA" },
          { type: "text", text: "world", text_elements: [] },
        ],
      }),
    ).toEqual([
      {
        sessionId: "s-1",
        update: {
          sessionUpdate: "user_message_chunk",
          content: { type: "text", text: "hello" },
        },
      },
      {
        sessionId: "s-1",
        update: {
          sessionUpdate: "user_message_chunk",
          content: { type: "text", text: "world" },
        },
      },
    ]);
  });

  it("replays a persisted plan item as a historical plan tool call", () => {
    expect(
      mapHistoryItem("s-1", { type: "plan", id: "p1", text: "# The plan" }),
    ).toEqual([
      {
        sessionId: "s-1",
        update: {
          sessionUpdate: "tool_call",
          toolCallId: "p1:implement",
          title: "Plan",
          kind: "switch_mode",
          status: "completed",
          content: [
            {
              type: "content",
              content: { type: "text", text: "# The plan" },
            },
          ],
          rawInput: { plan: "# The plan", historical: true },
        },
      },
    ]);
    expect(mapHistoryItem("s-1", { type: "plan", id: "p1" })).toEqual([]);
  });

  it("replays an agentMessage as an agent_message_chunk", () => {
    expect(
      mapHistoryItem("s-1", { type: "agentMessage", id: "a1", text: "done" }),
    ).toEqual([
      {
        sessionId: "s-1",
        update: {
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text: "done" },
        },
      },
    ]);
  });

  it("replays a completed command as one tool_call carrying status + output", () => {
    expect(
      mapHistoryItem("s-1", {
        type: "commandExecution",
        id: "c1",
        command: "ls -la",
        status: "completed",
        commandActions: [{ type: "read", path: "/repo/a.ts" }],
        aggregatedOutput: "a.ts\n",
      }),
    ).toEqual([
      {
        sessionId: "s-1",
        update: {
          sessionUpdate: "tool_call",
          toolCallId: "c1",
          title: "ls -la",
          kind: "read",
          status: "completed",
          locations: [{ path: "/repo/a.ts" }],
          content: [
            { type: "content", content: { type: "text", text: "a.ts\n" } },
          ],
        },
      },
    ]);
  });

  it("replays a fileChange as a tool_call with diff content", () => {
    const [update] = mapHistoryItem("s-1", {
      type: "fileChange",
      id: "f1",
      status: "completed",
      changes: [{ path: "a.txt", diff: "-x\n+y", kind: "modify" }],
    });
    expect(update.update).toMatchObject({
      sessionUpdate: "tool_call",
      toolCallId: "f1",
      kind: "edit",
      status: "completed",
      content: [{ type: "diff", path: "a.txt", oldText: "x", newText: "y" }],
    });
  });

  it("does not replay ephemeral reasoning items", () => {
    expect(mapHistoryItem("s-1", { type: "reasoning", id: "r1" })).toEqual([]);
  });
});

describe("parseUnifiedDiff", () => {
  it("keeps added/removed content lines whose payload starts with ++ or --", () => {
    expect(parseUnifiedDiff("@@ -1 +1 @@\n---count;\n+++count;")).toEqual({
      oldText: "--count;",
      newText: "++count;",
    });
  });

  it("skips file headers and the no-newline marker", () => {
    expect(
      parseUnifiedDiff(
        "--- a/x.ts\n+++ b/x.ts\n@@ -1 +1 @@\n-old\n+new\n\\ No newline at end of file",
      ),
    ).toEqual({ oldText: "old", newText: "new" });
  });
});

describe("mcpToolCall result rendering", () => {
  it("renders a completed mcpToolCall's result content as text", () => {
    expect(
      mapAppServerNotification("s-1", APP_SERVER_NOTIFICATIONS.ITEM_COMPLETED, {
        item: {
          type: "mcpToolCall",
          id: "m1",
          server: "posthog",
          tool: "query",
          status: "completed",
          arguments: { sql: "SELECT 1" },
          result: { content: [{ type: "text", text: "42 rows" }] },
        },
      }),
    ).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "tool_call_update",
        toolCallId: "m1",
        status: "completed",
        content: [
          { type: "content", content: { type: "text", text: "42 rows" } },
        ],
      },
    });
  });

  it("renders a failed mcpToolCall's error message", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.ITEM_COMPLETED,
      {
        item: {
          type: "mcpToolCall",
          id: "m2",
          server: "x",
          tool: "y",
          status: "failed",
          error: { message: "boom" },
        },
      },
    );
    expect(result?.update).toMatchObject({
      sessionUpdate: "tool_call_update",
      toolCallId: "m2",
      status: "failed",
      content: [{ type: "content", content: { type: "text", text: "boom" } }],
    });
  });

  it("renders a dynamicToolCall (not dropped) with its inputText output", () => {
    const result = mapAppServerNotification(
      "s-1",
      APP_SERVER_NOTIFICATIONS.ITEM_COMPLETED,
      {
        item: {
          type: "dynamicToolCall",
          id: "d1",
          namespace: "ns",
          tool: "doit",
          status: "completed",
          arguments: { x: 1 },
          contentItems: [{ type: "inputText", text: "result" }],
        },
      },
    );
    expect(result).toEqual({
      sessionId: "s-1",
      update: {
        sessionUpdate: "tool_call_update",
        toolCallId: "d1",
        status: "completed",
        content: [
          { type: "content", content: { type: "text", text: "result" } },
        ],
      },
    });
  });
});
