import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PostHogAPIClient } from "../../../posthog-api";
import type { StoredEntry } from "../../../types";
import {
  conversationTurnsToJsonlEntries,
  getSessionJsonlPath,
  hydrateSessionJsonl,
  rebuildConversation,
  sanitizeSessionJsonl,
  selectRecentTurns,
} from "./jsonl-hydration";

function entry(
  sessionUpdate: string,
  extra: Record<string, unknown> = {},
): StoredEntry {
  return {
    type: "notification",
    timestamp: new Date().toISOString(),
    notification: {
      jsonrpc: "2.0",
      method: "session/update",
      params: { update: { sessionUpdate, ...extra } },
    },
  };
}

function toolEntry(
  sessionUpdate: string,
  meta: Record<string, unknown>,
): StoredEntry {
  return entry(sessionUpdate, { _meta: { claudeCode: meta } });
}

describe("getSessionJsonlPath", () => {
  it("constructs path from sessionId and cwd", () => {
    const original = process.env.CLAUDE_CONFIG_DIR;
    process.env.CLAUDE_CONFIG_DIR = "/tmp/claude-test";
    try {
      const result = getSessionJsonlPath("sess-123", "/home/user/project");
      expect(result).toBe(
        "/tmp/claude-test/projects/-home-user-project/sess-123.jsonl",
      );
    } finally {
      if (original === undefined) delete process.env.CLAUDE_CONFIG_DIR;
      else process.env.CLAUDE_CONFIG_DIR = original;
    }
  });

  it("replaces dots and special chars like the Claude Code binary", () => {
    const original = process.env.CLAUDE_CONFIG_DIR;
    process.env.CLAUDE_CONFIG_DIR = "/tmp/claude-test";
    try {
      const result = getSessionJsonlPath(
        "sess-1",
        "/Users/dev/.posthog-code/worktrees/repo",
      );
      expect(result).toBe(
        "/tmp/claude-test/projects/-Users-dev--posthog-code-worktrees-repo/sess-1.jsonl",
      );
    } finally {
      if (original === undefined) delete process.env.CLAUDE_CONFIG_DIR;
      else process.env.CLAUDE_CONFIG_DIR = original;
    }
  });

  it("truncates long paths with hash like the Claude Code binary", () => {
    const original = process.env.CLAUDE_CONFIG_DIR;
    process.env.CLAUDE_CONFIG_DIR = "/tmp/claude-test";
    try {
      const longPath = `/home/${"a".repeat(250)}/project`;
      const result = getSessionJsonlPath("sess-1", longPath);
      const projectDir = result
        .replace("/tmp/claude-test/projects/", "")
        .replace("/sess-1.jsonl", "");
      expect(projectDir.length).toBeLessThanOrEqual(220);
      expect(projectDir).toMatch(/-[a-z0-9]+$/);
    } finally {
      if (original === undefined) delete process.env.CLAUDE_CONFIG_DIR;
      else process.env.CLAUDE_CONFIG_DIR = original;
    }
  });

  it("handles backslashes in cwd", () => {
    const original = process.env.CLAUDE_CONFIG_DIR;
    process.env.CLAUDE_CONFIG_DIR = "/tmp/claude-test";
    try {
      const result = getSessionJsonlPath("sess-1", "C:\\Users\\dev\\project");
      expect(result).toContain("C--Users-dev-project");
    } finally {
      if (original === undefined) delete process.env.CLAUDE_CONFIG_DIR;
      else process.env.CLAUDE_CONFIG_DIR = original;
    }
  });
});

describe("rebuildConversation", () => {
  it("returns empty turns for empty entries", () => {
    expect(rebuildConversation([])).toEqual([]);
  });

  it("returns empty turns for non-session/update entries", () => {
    const entries: StoredEntry[] = [
      {
        type: "notification",
        timestamp: new Date().toISOString(),
        notification: {
          jsonrpc: "2.0",
          method: "some/other_method",
          params: {},
        },
      },
    ];
    expect(rebuildConversation(entries)).toEqual([]);
  });

  it("produces a single user turn from user_message", () => {
    const turns = rebuildConversation([
      entry("user_message", {
        content: { type: "text", text: "hello" },
      }),
    ]);

    expect(turns).toHaveLength(1);
    expect(turns[0].role).toBe("user");
    expect(turns[0].content).toEqual([{ type: "text", text: "hello" }]);
  });

  it("handles user_message with array content", () => {
    const turns = rebuildConversation([
      entry("user_message", {
        content: [
          { type: "text", text: "first" },
          { type: "text", text: "second" },
        ],
      }),
    ]);

    expect(turns).toHaveLength(1);
    expect(turns[0].content).toHaveLength(2);
  });

  it("merges consecutive user messages into one turn", () => {
    const turns = rebuildConversation([
      entry("user_message", { content: { type: "text", text: "hello" } }),
      entry("user_message", { content: { type: "text", text: "world" } }),
      entry("agent_message", { content: { type: "text", text: "hi" } }),
    ]);

    expect(turns).toHaveLength(2);
    expect(turns[0].role).toBe("user");
    expect(turns[0].content).toEqual([
      { type: "text", text: "hello" },
      { type: "text", text: "world" },
    ]);
    expect(turns[1].role).toBe("assistant");
  });

  it("skips empty content in consecutive user messages", () => {
    const turns = rebuildConversation([
      entry("user_message", { content: { type: "text", text: "prompt" } }),
      entry("user_message", {}),
      entry("user_message", {}),
      entry("agent_message", { content: { type: "text", text: "response" } }),
    ]);

    expect(turns).toHaveLength(2);
    expect(turns[0].role).toBe("user");
    expect(turns[0].content).toEqual([{ type: "text", text: "prompt" }]);
  });

  it("coalesces consecutive agent text chunks", () => {
    const turns = rebuildConversation([
      entry("user_message", { content: { type: "text", text: "hi" } }),
      entry("agent_message_chunk", { content: { type: "text", text: "hel" } }),
      entry("agent_message_chunk", { content: { type: "text", text: "lo" } }),
      entry("agent_message_chunk", {
        content: { type: "text", text: " world" },
      }),
    ]);

    expect(turns).toHaveLength(2);
    expect(turns[1].role).toBe("assistant");
    expect(turns[1].content).toHaveLength(1);
    expect(turns[1].content[0]).toEqual({
      type: "text",
      text: "hello world",
    });
  });

  it("does not coalesce non-text blocks", () => {
    const turns = rebuildConversation([
      entry("user_message", { content: { type: "text", text: "hi" } }),
      entry("agent_message", {
        content: { type: "thinking", thinking: "hmm" },
      }),
      entry("agent_message", { content: { type: "text", text: "answer" } }),
    ]);

    expect(turns).toHaveLength(2);
    expect(turns[1].content).toHaveLength(2);
    expect(turns[1].content[0]).toEqual({ type: "thinking", thinking: "hmm" });
    expect(turns[1].content[1]).toEqual({ type: "text", text: "answer" });
  });

  it.each([
    { kind: "text", block: { type: "text", text: "" } },
    { kind: "thinking", block: { type: "thinking", thinking: "" } },
  ])("drops empty $kind blocks from assistant content", ({ block }) => {
    const turns = rebuildConversation([
      entry("user_message", { content: { type: "text", text: "hi" } }),
      entry("agent_thought_chunk", { content: block }),
      entry("agent_message_chunk", { content: { type: "text", text: "done" } }),
    ]);

    expect(turns).toHaveLength(2);
    expect(turns[1].content).toEqual([{ type: "text", text: "done" }]);
  });

  it("produces no assistant turn when every chunk is empty", () => {
    const turns = rebuildConversation([
      entry("user_message", { content: { type: "text", text: "q1" } }),
      entry("agent_thought_chunk", { content: { type: "text", text: "" } }),
      entry("user_message", { content: { type: "text", text: "q2" } }),
    ]);

    expect(turns).toHaveLength(1);
    expect(turns[0].role).toBe("user");
    expect(turns[0].content).toEqual([
      { type: "text", text: "q1" },
      { type: "text", text: "q2" },
    ]);
  });

  it("produces alternating user/assistant turns for multi-round conversation", () => {
    const turns = rebuildConversation([
      entry("user_message", { content: { type: "text", text: "q1" } }),
      entry("agent_message", { content: { type: "text", text: "a1" } }),
      entry("user_message", { content: { type: "text", text: "q2" } }),
      entry("agent_message", { content: { type: "text", text: "a2" } }),
    ]);

    expect(turns).toHaveLength(4);
    expect(turns.map((t) => t.role)).toEqual([
      "user",
      "assistant",
      "user",
      "assistant",
    ]);
  });

  it("tracks tool calls with results", () => {
    const turns = rebuildConversation([
      entry("user_message", { content: { type: "text", text: "do it" } }),
      entry("agent_message", { content: { type: "text", text: "ok" } }),
      toolEntry("tool_call", {
        toolCallId: "tc-1",
        toolName: "Bash",
        toolInput: { command: "ls" },
      }),
      toolEntry("tool_result", {
        toolCallId: "tc-1",
        toolResponse: "file.txt",
      }),
    ]);

    expect(turns).toHaveLength(2);
    const assistant = turns[1];
    expect(assistant.toolCalls).toHaveLength(1);
    expect(assistant.toolCalls?.[0]).toEqual({
      toolCallId: "tc-1",
      toolName: "Bash",
      input: { command: "ls" },
      result: "file.txt",
    });
  });

  it("updates tool result via tool_call_update", () => {
    const turns = rebuildConversation([
      entry("user_message", { content: { type: "text", text: "go" } }),
      toolEntry("tool_call", {
        toolCallId: "tc-1",
        toolName: "Read",
        toolInput: { path: "/a" },
      }),
      toolEntry("tool_call_update", {
        toolCallId: "tc-1",
        toolName: "Read",
        toolResponse: "contents",
      }),
    ]);

    expect(turns[1].toolCalls?.[0].result).toBe("contents");
  });

  it("flushes trailing assistant content", () => {
    const turns = rebuildConversation([
      entry("user_message", { content: { type: "text", text: "hi" } }),
      entry("agent_message", { content: { type: "text", text: "bye" } }),
    ]);

    expect(turns).toHaveLength(2);
    expect(turns[1].role).toBe("assistant");
    expect(turns[1].content[0]).toEqual({ type: "text", text: "bye" });
  });

  it("flushes trailing tool calls without explicit result", () => {
    const turns = rebuildConversation([
      entry("user_message", { content: { type: "text", text: "go" } }),
      toolEntry("tool_call", {
        toolCallId: "tc-1",
        toolName: "Bash",
        toolInput: { command: "echo" },
      }),
    ]);

    expect(turns).toHaveLength(2);
    expect(turns[1].toolCalls).toHaveLength(1);
    expect(turns[1].toolCalls?.[0].result).toBeUndefined();
  });

  it("tracks tool calls from the ACP shape: top-level toolCallId/rawInput/rawOutput, toolName in _meta", () => {
    // Mirrors the exact update sequence agent-server persists to S3. Before
    // the top-level fields were read, every tool call was dropped and a
    // 30-minute run resumed as a 4-line transcript.
    const turns = rebuildConversation([
      entry("user_message", { content: { type: "text", text: "fix it" } }),
      entry("tool_call", {
        toolCallId: "toolu_01",
        _meta: { claudeCode: { toolName: "Bash" } },
        rawInput: {},
        status: "pending",
        title: "Execute command",
        kind: "execute",
        content: [],
      }),
      entry("tool_call_update", {
        toolCallId: "toolu_01",
        rawInput: { command: "gh pr view 123" },
      }),
      entry("tool_call_update", {
        toolCallId: "toolu_01",
        _meta: { claudeCode: { toolName: "Bash" } },
        status: "completed",
        rawOutput: { stdout: "PR title" },
      }),
    ]);

    expect(turns).toHaveLength(2);
    expect(turns[1].toolCalls).toEqual([
      {
        toolCallId: "toolu_01",
        toolName: "Bash",
        input: { command: "gh pr view 123" },
        result: { stdout: "PR title" },
      },
    ]);
  });

  it("truncates oversized tool payloads, keeping object inputs as objects", () => {
    const bigOutput = "x".repeat(50_000);
    const bigInput = { file_path: "/tmp/big.ts", content: "y".repeat(50_000) };
    const turns = rebuildConversation([
      entry("user_message", { content: { type: "text", text: "go" } }),
      entry("tool_call", {
        toolCallId: "toolu_01",
        _meta: { claudeCode: { toolName: "Write" } },
        rawInput: bigInput,
      }),
      entry("tool_call_update", {
        toolCallId: "toolu_01",
        rawOutput: bigOutput,
      }),
    ]);

    // String outputs may truncate to a string; tool_use.input must stay an
    // object per the Claude API schema.
    const result = turns[1].toolCalls?.[0].result as string;
    expect(result.length).toBeLessThan(11_000);
    expect(result).toContain("[truncated");

    const input = turns[1].toolCalls?.[0].input as {
      _truncated: boolean;
      preview: string;
      originalSize: number;
    };
    expect(input._truncated).toBe(true);
    expect(input.preview.length).toBeLessThan(11_000);
    expect(input.originalSize).toBeGreaterThan(50_000);
  });
});

describe("selectRecentTurns", () => {
  it("keeps the user turn and sheds oldest tool calls when the final turn alone exceeds the budget", () => {
    // A single-prompt run rebuilds into [user, one giant assistant turn].
    // Before the fallback, that shape selected zero turns and hydration
    // wrote an empty transcript.
    const bigInput = { data: "y".repeat(8_000) };
    const turns = rebuildConversation([
      entry("user_message", { content: { type: "text", text: "the task" } }),
      ...[1, 2, 3].map((i) =>
        entry("tool_call", {
          toolCallId: `toolu_0${i}`,
          _meta: { claudeCode: { toolName: "Bash" } },
          rawInput: bigInput,
        }),
      ),
    ]);

    // Budget fits the user turn plus roughly one big tool call.
    const selected = selectRecentTurns(turns, 3_000);

    expect(selected).toHaveLength(2);
    expect(selected[0].role).toBe("user");
    expect(selected[1].role).toBe("assistant");
    const keptIds = selected[1].toolCalls?.map((tc) => tc.toolCallId);
    expect(keptIds).toEqual(["toolu_03"]);
  });

  it("returns recent turns that fit the budget unchanged", () => {
    const turns = [
      {
        role: "user" as const,
        content: [{ type: "text" as const, text: "a" }],
      },
      {
        role: "assistant" as const,
        content: [{ type: "text" as const, text: "b" }],
      },
    ];
    expect(selectRecentTurns(turns, 1_000)).toEqual(turns);
  });
});

describe("conversationTurnsToJsonlEntries", () => {
  const config = { sessionId: "sess-1", cwd: "/repo" };

  function parseConversationEntries(lines: string[]) {
    return lines
      .map((l) => JSON.parse(l))
      .filter((e: { type: string }) => e.type !== "queue-operation");
  }

  function parseQueueEntries(lines: string[]) {
    return lines
      .map((l) => JSON.parse(l))
      .filter((e: { type: string }) => e.type === "queue-operation");
  }

  it("returns empty array for empty turns", () => {
    expect(conversationTurnsToJsonlEntries([], config)).toEqual([]);
  });

  it("produces queue ops and a user line with array content", () => {
    const lines = conversationTurnsToJsonlEntries(
      [{ role: "user", content: [{ type: "text", text: "hello" }] }],
      config,
    );

    // enqueue + dequeue + user entry
    expect(lines).toHaveLength(3);

    const queueOps = parseQueueEntries(lines);
    expect(queueOps).toHaveLength(2);
    expect(queueOps[0].operation).toBe("enqueue");
    expect(queueOps[1].operation).toBe("dequeue");
    expect(queueOps[0].sessionId).toBe("sess-1");

    const [parsed] = parseConversationEntries(lines);
    expect(parsed.type).toBe("user");
    expect(parsed.message.role).toBe("user");
    expect(parsed.message.content).toEqual([{ type: "text", text: "hello" }]);
    expect(parsed.sessionId).toBe("sess-1");
    expect(parsed.cwd).toBe("/repo");
    expect(parsed.parentUuid).toBeNull();
    expect(parsed.version).toBe("2.1.63");
    expect(parsed.permissionMode).toBe("default");
    expect(parsed.gitBranch).toBeDefined();
    expect(parsed.slug).toBeDefined();
  });

  it("chains parentUuid across conversation entries", () => {
    const lines = conversationTurnsToJsonlEntries(
      [
        { role: "user", content: [{ type: "text", text: "q" }] },
        { role: "assistant", content: [{ type: "text", text: "a" }] },
      ],
      config,
    );

    const conv = parseConversationEntries(lines);
    expect(conv[0].parentUuid).toBeNull();
    expect(conv[1].parentUuid).toBe(conv[0].uuid);
  });

  it("emits one line per assistant block with shared message id", () => {
    const lines = conversationTurnsToJsonlEntries(
      [
        {
          role: "assistant",
          content: [{ type: "text", text: "running" }],
          toolCalls: [
            {
              toolCallId: "tc-1",
              toolName: "Bash",
              input: { command: "ls" },
              result: "output",
            },
          ],
        },
      ],
      config,
    );

    // No queue ops for assistant-only turn; text + tool_use + tool_result
    const conv = parseConversationEntries(lines);
    expect(conv).toHaveLength(3);

    expect(conv[0].type).toBe("assistant");
    expect(conv[0].message.content).toEqual([
      { type: "text", text: "running" },
    ]);
    expect(conv[0].message.stop_reason).toBeNull();
    expect(conv[0].message.model).toBe("claude-opus-4-8");
    expect(conv[0].message.id).toMatch(/^msg_01[A-Za-z0-9]{24}$/);

    expect(conv[1].type).toBe("assistant");
    expect(conv[1].message.content).toEqual([
      {
        type: "tool_use",
        id: "tc-1",
        name: "Bash",
        input: { command: "ls" },
      },
    ]);
    expect(conv[1].message.stop_reason).toBe("tool_use");
    expect(conv[1].message.id).toBe(conv[0].message.id);

    expect(conv[2].type).toBe("user");
    expect(conv[2].message.content[0]).toEqual({
      type: "tool_result",
      tool_use_id: "tc-1",
      content: "output",
    });
    expect(conv[2].parentUuid).toBe(conv[1].uuid);
  });

  it.each([undefined, null])(
    "emits input: {} for tool calls whose input is %s",
    (missingInput) => {
      const lines = conversationTurnsToJsonlEntries(
        [
          {
            role: "assistant",
            content: [],
            toolCalls: [
              { toolCallId: "tc-1", toolName: "Bash", input: missingInput },
            ],
          },
        ],
        config,
      );

      const conv = parseConversationEntries(lines);
      expect(conv).toHaveLength(1);
      expect(conv[0].message.content).toEqual([
        { type: "tool_use", id: "tc-1", name: "Bash", input: {} },
      ]);
    },
  );

  it("sets stop_reason only on last block, null on intermediate", () => {
    const lines = conversationTurnsToJsonlEntries(
      [
        {
          role: "assistant",
          content: [
            { type: "thinking", thinking: "hmm" } as unknown as {
              type: "text";
              text: string;
            },
            { type: "text", text: "answer" },
          ],
        },
      ],
      config,
    );

    const conv = parseConversationEntries(lines);
    expect(conv).toHaveLength(2);
    expect(conv[0].message.stop_reason).toBeNull();
    expect(conv[1].message.stop_reason).toBe("end_turn");
    expect(conv[0].message.id).toBe(conv[1].message.id);
  });

  it("skips tool results that are undefined", () => {
    const lines = conversationTurnsToJsonlEntries(
      [
        {
          role: "assistant",
          content: [{ type: "text", text: "x" }],
          toolCalls: [
            {
              toolCallId: "tc-1",
              toolName: "Bash",
              input: {},
            },
          ],
        },
      ],
      config,
    );

    const conv = parseConversationEntries(lines);
    expect(conv).toHaveLength(2);
    expect(conv[0].type).toBe("assistant");
    expect(conv[1].type).toBe("assistant");
    expect(conv[1].message.content[0].type).toBe("tool_use");
  });

  it("serializes non-string tool results as JSON", () => {
    const lines = conversationTurnsToJsonlEntries(
      [
        {
          role: "assistant",
          content: [{ type: "text", text: "x" }],
          toolCalls: [
            {
              toolCallId: "tc-1",
              toolName: "Read",
              input: {},
              result: { files: ["a.ts"] },
            },
          ],
        },
      ],
      config,
    );

    const conv = parseConversationEntries(lines);
    expect(conv[2].message.content[0].content).toBe(
      JSON.stringify({ files: ["a.ts"] }),
    );
  });

  it("falls back to space for empty user content", () => {
    const lines = conversationTurnsToJsonlEntries(
      [{ role: "user", content: [] }],
      config,
    );

    const [parsed] = parseConversationEntries(lines);
    expect(parsed.message.content).toEqual([{ type: "text", text: " " }]);
  });

  it.each([
    { kind: "text", block: { type: "text", text: "" } },
    { kind: "thinking", block: { type: "thinking", thinking: "" } },
  ])("drops empty $kind blocks from assistant lines", ({ block }) => {
    const lines = conversationTurnsToJsonlEntries(
      [
        { role: "user", content: [{ type: "text", text: "hi" }] },
        {
          role: "assistant",
          content: [
            block as unknown as { type: "text"; text: string },
            { type: "text", text: "answer" },
          ],
        },
      ],
      config,
    );

    const conv = parseConversationEntries(lines);
    expect(conv).toHaveLength(2);
    expect(conv[1].message.content).toEqual([{ type: "text", text: "answer" }]);
    expect(conv[1].message.stop_reason).toBe("end_turn");
  });

  it("emits only tool lines when all content blocks are empty", () => {
    const lines = conversationTurnsToJsonlEntries(
      [
        {
          role: "assistant",
          content: [{ type: "text", text: "" }],
          toolCalls: [
            {
              toolCallId: "tc-1",
              toolName: "Bash",
              input: { command: "ls" },
              result: "out",
            },
          ],
        },
      ],
      config,
    );

    const conv = parseConversationEntries(lines);
    expect(conv).toHaveLength(2);
    expect(conv[0].message.content[0].type).toBe("tool_use");
    expect(conv[0].message.stop_reason).toBe("tool_use");
    expect(conv[1].message.content[0].type).toBe("tool_result");
  });

  it("emits no assistant lines when all blocks are empty and there are no tool calls", () => {
    const lines = conversationTurnsToJsonlEntries(
      [
        { role: "user", content: [{ type: "text", text: "hi" }] },
        { role: "assistant", content: [{ type: "text", text: "" }] },
      ],
      config,
    );

    const conv = parseConversationEntries(lines);
    expect(conv).toHaveLength(1);
    expect(conv[0].type).toBe("user");
  });

  it("produces no empty content blocks from logs containing empty thought chunks", () => {
    const turns = rebuildConversation([
      entry("user_message", { content: { type: "text", text: "fix the bug" } }),
      entry("agent_thought_chunk", { content: { type: "text", text: "" } }),
      entry("agent_message_chunk", {
        content: { type: "text", text: "on it" },
      }),
    ]);
    const lines = conversationTurnsToJsonlEntries(turns, config);

    const conv = parseConversationEntries(lines);
    expect(conv.length).toBeGreaterThan(0);
    for (const parsed of conv) {
      for (const block of parsed.message.content) {
        if (block.type === "text") expect(block.text).not.toBe("");
        if (block.type === "thinking") expect(block.thinking).not.toBe("");
      }
    }
  });

  it("uses custom model and version from config", () => {
    const lines = conversationTurnsToJsonlEntries(
      [
        { role: "user", content: [{ type: "text", text: "hi" }] },
        { role: "assistant", content: [{ type: "text", text: "hello" }] },
      ],
      { sessionId: "s", cwd: "/", model: "claude-opus-4-7", version: "3.0.0" },
    );

    const conv = parseConversationEntries(lines);
    expect(conv[0].version).toBe("3.0.0");
    expect(conv[1].version).toBe("3.0.0");
    expect(conv[1].message.model).toBe("claude-opus-4-7");
  });

  it("passes gitBranch, slug and permissionMode from config", () => {
    const lines = conversationTurnsToJsonlEntries(
      [
        { role: "user", content: [{ type: "text", text: "hi" }] },
        { role: "assistant", content: [{ type: "text", text: "hello" }] },
      ],
      {
        sessionId: "s",
        cwd: "/",
        gitBranch: "feat/test",
        slug: "custom-slug-name",
        permissionMode: "plan",
      },
    );

    const conv = parseConversationEntries(lines);
    // User entry
    expect(conv[0].gitBranch).toBe("feat/test");
    expect(conv[0].slug).toBe("custom-slug-name");
    expect(conv[0].permissionMode).toBe("plan");
    // Assistant entry
    expect(conv[1].gitBranch).toBe("feat/test");
    expect(conv[1].slug).toBe("custom-slug-name");
    // Assistant entries don't have permissionMode
    expect(conv[1].permissionMode).toBeUndefined();
  });
});

describe("end-to-end: S3 log entries -> JSONL output", () => {
  const config = { sessionId: "sess-abc", cwd: "/home/user/repo" };

  function s3Entry(
    sessionUpdate: string,
    extra: Record<string, unknown> = {},
  ): StoredEntry {
    return {
      type: "notification",
      timestamp: "2026-03-03T12:00:00.000Z",
      notification: {
        jsonrpc: "2.0",
        method: "session/update",
        params: { update: { sessionUpdate, ...extra } },
      },
    };
  }

  function filterConv(parsed: Record<string, unknown>[]) {
    return parsed.filter((e) => e.type !== "queue-operation");
  }

  function filterQueue(parsed: Record<string, unknown>[]) {
    return parsed.filter((e) => e.type === "queue-operation");
  }

  it("converts a multi-turn session with tool use into valid JSONL", () => {
    const s3Logs: StoredEntry[] = [
      s3Entry("user_message", {
        content: { type: "text", text: "List the files in src/" },
      }),
      s3Entry("agent_message_chunk", {
        content: { type: "thinking", thinking: "I should use Bash to run ls" },
      }),
      s3Entry("agent_message_chunk", {
        content: { type: "text", text: "I'll list the files " },
      }),
      s3Entry("agent_message_chunk", {
        content: { type: "text", text: "for you." },
      }),
      s3Entry("tool_call", {
        _meta: {
          claudeCode: {
            toolCallId: "toolu_01ABC",
            toolName: "Bash",
            toolInput: { command: "ls src/" },
          },
        },
      }),
      s3Entry("tool_result", {
        _meta: {
          claudeCode: {
            toolCallId: "toolu_01ABC",
            toolResponse: "index.ts\nutils.ts\nconfig.ts",
          },
        },
      }),
      s3Entry("agent_message", {
        content: {
          type: "text",
          text: "There are 3 files: index.ts, utils.ts and config.ts.",
        },
      }),
      s3Entry("user_message", {
        content: { type: "text", text: "Read index.ts" },
      }),
      s3Entry("agent_message_chunk", {
        content: { type: "text", text: "Reading now." },
      }),
      s3Entry("tool_call", {
        _meta: {
          claudeCode: {
            toolCallId: "toolu_02DEF",
            toolName: "Read",
            toolInput: { file_path: "/home/user/repo/src/index.ts" },
          },
        },
      }),
      s3Entry("tool_result", {
        _meta: {
          claudeCode: {
            toolCallId: "toolu_02DEF",
            toolResponse: 'export const main = () => console.log("hello");',
          },
        },
      }),
      s3Entry("agent_message", {
        content: {
          type: "text",
          text: "The file exports a main function that logs hello.",
        },
      }),
    ];

    const turns = rebuildConversation(s3Logs);
    const lines = conversationTurnsToJsonlEntries(turns, config);
    const allParsed = lines.map((l) => JSON.parse(l));
    const conv = filterConv(allParsed);
    const queueOps = filterQueue(allParsed);

    expect(turns).toHaveLength(4);
    expect(turns.map((t) => t.role)).toEqual([
      "user",
      "assistant",
      "user",
      "assistant",
    ]);

    const firstAssistant = turns[1];
    const thinkingBlocks = firstAssistant.content.filter(
      (b) =>
        typeof b === "object" &&
        b !== null &&
        "type" in b &&
        (b as { type: string }).type === "thinking",
    );
    expect(thinkingBlocks).toHaveLength(1);

    const textBlocks = firstAssistant.content.filter(
      (b) =>
        typeof b === "object" && b !== null && "type" in b && b.type === "text",
    );
    expect(textBlocks).toHaveLength(1);
    const firstText = (textBlocks[0] as { type: "text"; text: string }).text;
    expect(firstText).toContain("I'll list the files for you.");
    expect(firstText).toContain("There are 3 files");

    expect(firstAssistant.toolCalls).toHaveLength(1);
    expect(firstAssistant.toolCalls?.[0].toolName).toBe("Bash");
    expect(firstAssistant.toolCalls?.[0].result).toBe(
      "index.ts\nutils.ts\nconfig.ts",
    );

    // 2 user turns → 4 queue-operation entries (enqueue + dequeue each)
    expect(queueOps).toHaveLength(4);

    // Conversation entries (excluding queue ops):
    // user, thinking, text, tool_use(Bash), tool_result(Bash),
    // user, text, tool_use(Read), tool_result(Read)
    const types = conv.map((p) => p.type);
    expect(types).toEqual([
      "user",
      "assistant",
      "assistant",
      "assistant",
      "user",
      "user",
      "assistant",
      "assistant",
      "user",
    ]);

    // Verify parentUuid chaining (only conversation entries participate)
    expect(conv[0].parentUuid).toBeNull();
    for (let i = 1; i < conv.length; i++) {
      expect(conv[i].parentUuid).toBe(conv[i - 1].uuid);
    }

    // Verify all conversation entries have required fields
    for (const e of conv) {
      expect(e.sessionId).toBe("sess-abc");
      expect(e.cwd).toBe("/home/user/repo");
      expect(e.isSidechain).toBe(false);
      expect(e.uuid).toBeDefined();
      expect(e.timestamp).toBeDefined();
      expect(e.version).toBe("2.1.63");
      expect(e.gitBranch).toBeDefined();
      expect(e.slug).toBeDefined();
      expect(typeof e.slug).toBe("string");
    }

    // Verify first user message content (array format)
    expect((conv[0].message as Record<string, unknown>).content).toEqual([
      { type: "text", text: "List the files in src/" },
    ]);

    // Verify thinking block: stop_reason null (intermediate)
    const msg1 = conv[1].message as Record<string, unknown>;
    expect((msg1.content as unknown[])[0]).toMatchObject({ type: "thinking" });
    expect(msg1.stop_reason).toBeNull();

    // Verify text block: stop_reason null (intermediate)
    const msg2 = conv[2].message as Record<string, unknown>;
    expect((msg2.content as unknown[])[0]).toMatchObject({ type: "text" });
    expect(msg2.stop_reason).toBeNull();

    // Verify tool_use block: stop_reason "tool_use" (last block in turn)
    const msg3 = conv[3].message as Record<string, unknown>;
    expect(msg3.content).toEqual([
      {
        type: "tool_use",
        id: "toolu_01ABC",
        name: "Bash",
        input: { command: "ls src/" },
      },
    ]);
    expect(msg3.stop_reason).toBe("tool_use");

    // All assistant blocks in same turn share message.id
    expect(msg1.id).toBe(msg2.id);
    expect(msg2.id).toBe(msg3.id);
    expect(msg3.model).toBe("claude-opus-4-8");
    expect(msg3.id).toMatch(/^msg_01[A-Za-z0-9]{24}$/);

    // Verify Bash tool_result entry
    const msg4 = conv[4].message as {
      content: { tool_use_id: string; content: string; type: string }[];
    };
    expect(msg4.content[0]).toEqual({
      type: "tool_result",
      tool_use_id: "toolu_01ABC",
      content: "index.ts\nutils.ts\nconfig.ts",
    });

    // Verify second user message (array format)
    expect((conv[5].message as Record<string, unknown>).content).toEqual([
      { type: "text", text: "Read index.ts" },
    ]);

    // Second assistant turn blocks share a different message.id
    const msg6 = conv[6].message as Record<string, unknown>;
    const msg7 = conv[7].message as Record<string, unknown>;
    expect(msg6.id).toBe(msg7.id);
    expect(msg6.id).not.toBe(msg1.id);

    // Verify Read tool_result entry
    const msg8 = conv[8].message as {
      content: { tool_use_id: string; content: string; type: string }[];
    };
    expect(msg8.content[0]).toEqual({
      type: "tool_result",
      tool_use_id: "toolu_02DEF",
      content: 'export const main = () => console.log("hello");',
    });
  });

  it("handles a session with only user messages and no agent response", () => {
    const s3Logs: StoredEntry[] = [
      s3Entry("user_message", {
        content: { type: "text", text: "hello" },
      }),
    ];

    const turns = rebuildConversation(s3Logs);
    const lines = conversationTurnsToJsonlEntries(turns, config);
    const conv = filterConv(lines.map((l) => JSON.parse(l)));

    expect(turns).toHaveLength(1);
    // enqueue + dequeue + user = 3 total lines, 1 conversation entry
    expect(lines).toHaveLength(3);
    expect(conv).toHaveLength(1);

    expect(conv[0].type).toBe("user");
    expect((conv[0].message as Record<string, unknown>).content).toEqual([
      { type: "text", text: "hello" },
    ]);
  });

  it("handles interleaved non-session/update entries gracefully", () => {
    const s3Logs: StoredEntry[] = [
      s3Entry("user_message", {
        content: { type: "text", text: "hi" },
      }),
      {
        type: "notification",
        timestamp: "2026-03-03T12:00:01.000Z",
        notification: {
          jsonrpc: "2.0",
          method: "_posthog/phase_start",
          params: { phase: "research" },
        },
      },
      s3Entry("agent_message", {
        content: { type: "text", text: "hello back" },
      }),
    ];

    const turns = rebuildConversation(s3Logs);
    expect(turns).toHaveLength(2);
    expect(turns[0].role).toBe("user");
    expect(turns[1].role).toBe("assistant");

    const lines = conversationTurnsToJsonlEntries(turns, config);
    const conv = filterConv(lines.map((l) => JSON.parse(l)));
    // 1 user turn → 2 queue ops + user + assistant = 4 total, 2 conversation
    expect(lines).toHaveLength(4);
    expect(conv).toHaveLength(2);
  });

  it("handles multiple tool calls in a single assistant turn", () => {
    const s3Logs: StoredEntry[] = [
      s3Entry("user_message", {
        content: { type: "text", text: "check both files" },
      }),
      s3Entry("agent_message", {
        content: { type: "text", text: "Reading both." },
      }),
      s3Entry("tool_call", {
        _meta: {
          claudeCode: {
            toolCallId: "tc-a",
            toolName: "Read",
            toolInput: { file_path: "/a.ts" },
          },
        },
      }),
      s3Entry("tool_call", {
        _meta: {
          claudeCode: {
            toolCallId: "tc-b",
            toolName: "Read",
            toolInput: { file_path: "/b.ts" },
          },
        },
      }),
      s3Entry("tool_result", {
        _meta: { claudeCode: { toolCallId: "tc-a", toolResponse: "aaa" } },
      }),
      s3Entry("tool_result", {
        _meta: { claudeCode: { toolCallId: "tc-b", toolResponse: "bbb" } },
      }),
    ];

    const turns = rebuildConversation(s3Logs);
    expect(turns).toHaveLength(2);

    const assistant = turns[1];
    expect(assistant.toolCalls).toHaveLength(2);
    expect(assistant.toolCalls?.[0]).toMatchObject({
      toolCallId: "tc-a",
      result: "aaa",
    });
    expect(assistant.toolCalls?.[1]).toMatchObject({
      toolCallId: "tc-b",
      result: "bbb",
    });

    const lines = conversationTurnsToJsonlEntries(turns, config);
    const conv = filterConv(lines.map((l) => JSON.parse(l)));

    // user, text, tool_use(a), tool_use(b), tool_result(a), tool_result(b)
    expect(conv).toHaveLength(6);
    expect(conv.map((p) => p.type)).toEqual([
      "user",
      "assistant",
      "assistant",
      "assistant",
      "user",
      "user",
    ]);

    // Text block: stop_reason null (intermediate)
    expect((conv[1].message as Record<string, unknown>).stop_reason).toBeNull();

    // First tool_use: stop_reason null (intermediate)
    const msg2 = conv[2].message as Record<string, unknown>;
    expect(msg2.stop_reason).toBeNull();
    expect(((msg2.content as unknown[])[0] as Record<string, unknown>).id).toBe(
      "tc-a",
    );

    // Last tool_use: stop_reason "tool_use" (last block)
    const msg3 = conv[3].message as Record<string, unknown>;
    expect(msg3.stop_reason).toBe("tool_use");
    expect(((msg3.content as unknown[])[0] as Record<string, unknown>).id).toBe(
      "tc-b",
    );

    // All share same message.id
    const msg1 = conv[1].message as Record<string, unknown>;
    expect(msg1.id).toBe(msg2.id);
    expect(msg2.id).toBe(msg3.id);
  });

  it("emits input: {} when the tool input never reached the logs", () => {
    const s3Logs: StoredEntry[] = [
      s3Entry("user_message", {
        content: { type: "text", text: "run the tests" },
      }),
      s3Entry("tool_call", {
        toolCallId: "tc-lost",
        _meta: { claudeCode: { toolName: "Bash" } },
      }),
    ];

    const turns = rebuildConversation(s3Logs);
    const lines = conversationTurnsToJsonlEntries(turns, config);
    const conv = filterConv(lines.map((l) => JSON.parse(l)));

    const toolUseLine = conv.find((e) => e.type === "assistant");
    expect(toolUseLine).toBeDefined();
    const content = (toolUseLine?.message as { content: unknown[] }).content;
    expect(content).toEqual([
      { type: "tool_use", id: "tc-lost", name: "Bash", input: {} },
    ]);
  });
});

describe("sanitizeSessionJsonl", () => {
  let dir: string;

  beforeEach(async () => {
    dir = await fs.mkdtemp(path.join(os.tmpdir(), "jsonl-sanitize-"));
  });

  afterEach(async () => {
    await fs.rm(dir, { recursive: true, force: true });
  });

  async function writeJsonl(lines: unknown[]): Promise<string> {
    const file = path.join(dir, "sess.jsonl");
    await fs.writeFile(
      file,
      `${lines.map((l) => (typeof l === "string" ? l : JSON.stringify(l))).join("\n")}\n`,
    );
    return file;
  }

  async function readJsonl(file: string): Promise<Record<string, unknown>[]> {
    const raw = await fs.readFile(file, "utf8");
    return raw
      .split("\n")
      .filter((l) => l.trim())
      .map((l) => JSON.parse(l));
  }

  it("removes empty text and thinking blocks from existing files", async () => {
    const file = await writeJsonl([
      {
        type: "user",
        uuid: "u1",
        parentUuid: null,
        message: { role: "user", content: [{ type: "text", text: "hi" }] },
      },
      {
        type: "assistant",
        uuid: "a1",
        parentUuid: "u1",
        message: {
          role: "assistant",
          content: [
            { type: "thinking", thinking: "" },
            { type: "text", text: "hello" },
          ],
        },
      },
    ]);

    expect(await sanitizeSessionJsonl(file)).toBe(true);

    const raw = await fs.readFile(file, "utf8");
    expect(raw.endsWith("\n")).toBe(true);

    const lines = await readJsonl(file);
    expect(lines[0].message).toEqual({
      role: "user",
      content: [{ type: "text", text: "hi" }],
    });
    const assistant = lines[1].message as { content: unknown };
    expect(assistant.content).toEqual([{ type: "text", text: "hello" }]);
    expect(lines[1].uuid).toBe("a1");
    expect(lines[1].parentUuid).toBe("u1");
  });

  it("replaces all-empty content with a single space block", async () => {
    const file = await writeJsonl([
      {
        type: "assistant",
        uuid: "a1",
        parentUuid: null,
        message: { role: "assistant", content: [{ type: "text", text: "" }] },
      },
    ]);

    expect(await sanitizeSessionJsonl(file)).toBe(true);

    const lines = await readJsonl(file);
    const assistant = lines[0].message as { content: unknown };
    expect(assistant.content).toEqual([{ type: "text", text: " " }]);
  });

  it("keeps tool_use blocks while stripping empty siblings", async () => {
    const file = await writeJsonl([
      {
        type: "assistant",
        uuid: "a1",
        parentUuid: null,
        message: {
          role: "assistant",
          content: [
            { type: "tool_use", id: "tc-1", name: "Bash", input: {} },
            { type: "text", text: "" },
          ],
        },
      },
    ]);

    expect(await sanitizeSessionJsonl(file)).toBe(true);

    const lines = await readJsonl(file);
    const assistant = lines[0].message as { content: unknown };
    expect(assistant.content).toEqual([
      { type: "tool_use", id: "tc-1", name: "Bash", input: {} },
    ]);
  });

  it.each([
    ["a missing", { type: "tool_use", id: "tc-1", name: "Bash" }],
    ["a null", { type: "tool_use", id: "tc-1", name: "Bash", input: null }],
  ])("adds input: {} to tool_use blocks with %s input", async (_, block) => {
    const file = await writeJsonl([
      {
        type: "assistant",
        uuid: "a1",
        parentUuid: null,
        message: {
          role: "assistant",
          content: [{ type: "text", text: "running" }, block],
        },
      },
    ]);

    expect(await sanitizeSessionJsonl(file)).toBe(true);

    const lines = await readJsonl(file);
    const assistant = lines[0].message as { content: unknown };
    expect(assistant.content).toEqual([
      { type: "text", text: "running" },
      { type: "tool_use", id: "tc-1", name: "Bash", input: {} },
    ]);
  });

  it("sanitizes empty blocks in user lines too", async () => {
    const file = await writeJsonl([
      {
        type: "user",
        uuid: "u1",
        parentUuid: null,
        message: {
          role: "user",
          content: [
            { type: "text", text: "" },
            { type: "text", text: "prompt" },
          ],
        },
      },
    ]);

    expect(await sanitizeSessionJsonl(file)).toBe(true);

    const lines = await readJsonl(file);
    const user = lines[0].message as { content: unknown };
    expect(user.content).toEqual([{ type: "text", text: "prompt" }]);
  });

  it("preserves unparseable lines while fixing valid ones", async () => {
    const corruptLine = '{"type":"assistant","message":';
    const file = await writeJsonl([
      corruptLine,
      {
        type: "assistant",
        uuid: "a1",
        parentUuid: null,
        message: { role: "assistant", content: [{ type: "text", text: "" }] },
      },
    ]);

    expect(await sanitizeSessionJsonl(file)).toBe(true);

    const raw = await fs.readFile(file, "utf8");
    const rawLines = raw.split("\n").filter((l) => l.trim());
    expect(rawLines[0]).toBe(corruptLine);
    const assistant = JSON.parse(rawLines[1]).message as { content: unknown };
    expect(assistant.content).toEqual([{ type: "text", text: " " }]);
  });

  it("passes through string message content", async () => {
    const file = await writeJsonl([
      {
        type: "assistant",
        uuid: "a1",
        parentUuid: null,
        message: { role: "assistant", content: "" },
      },
    ]);
    const before = await fs.readFile(file, "utf8");

    expect(await sanitizeSessionJsonl(file)).toBe(false);
    expect(await fs.readFile(file, "utf8")).toBe(before);
  });

  it("leaves clean files unchanged", async () => {
    const file = await writeJsonl([
      { type: "queue-operation", operation: "enqueue" },
      {
        type: "assistant",
        uuid: "a1",
        parentUuid: null,
        message: { role: "assistant", content: [{ type: "text", text: "ok" }] },
      },
    ]);
    const before = await fs.readFile(file, "utf8");

    expect(await sanitizeSessionJsonl(file)).toBe(false);
    expect(await fs.readFile(file, "utf8")).toBe(before);
  });

  it("neutralizes an oversized image nested in a tool_result", async () => {
    // A Read on a big image file lands its bytes inside a tool_result; on
    // resume that block 400s every turn until it is replaced.
    const oversized = "A".repeat(6 * 1024 * 1024 * (4 / 3));
    const file = await writeJsonl([
      {
        type: "user",
        uuid: "u1",
        parentUuid: null,
        message: {
          role: "user",
          content: [
            {
              type: "tool_result",
              tool_use_id: "tc-1",
              content: [
                {
                  type: "image",
                  source: {
                    type: "base64",
                    media_type: "image/png",
                    data: oversized,
                  },
                },
              ],
            },
          ],
        },
      },
    ]);

    expect(await sanitizeSessionJsonl(file)).toBe(true);

    const lines = await readJsonl(file);
    const user = lines[0].message as {
      content: [{ content: unknown[] }];
    };
    expect(user.content[0].content).toEqual([
      {
        type: "text",
        text: "[Removed unprocessable image: image exceeds the 5 MB per-image limit]",
      },
    ]);
  });

  it("neutralizes an unsupported top-level image mime type", async () => {
    const file = await writeJsonl([
      {
        type: "user",
        uuid: "u1",
        parentUuid: null,
        message: {
          role: "user",
          content: [
            { type: "text", text: "look" },
            { type: "image", data: "abc", mimeType: "image/tiff" },
          ],
        },
      },
    ]);

    expect(await sanitizeSessionJsonl(file)).toBe(true);

    const lines = await readJsonl(file);
    const user = lines[0].message as { content: unknown };
    expect(user.content).toEqual([
      { type: "text", text: "look" },
      {
        type: "text",
        text: "[Removed unprocessable image: unsupported image type image/tiff]",
      },
    ]);
  });

  it("neutralizes an image with empty base64 data", async () => {
    const file = await writeJsonl([
      {
        type: "user",
        uuid: "u1",
        parentUuid: null,
        message: {
          role: "user",
          content: [
            {
              type: "image",
              source: { type: "base64", media_type: "image/png", data: "" },
            },
          ],
        },
      },
    ]);

    expect(await sanitizeSessionJsonl(file)).toBe(true);

    const lines = await readJsonl(file);
    const user = lines[0].message as { content: unknown };
    expect(user.content).toEqual([
      {
        type: "text",
        text: "[Removed unprocessable image: image data is empty]",
      },
    ]);
  });

  it("leaves a small, supported image untouched", async () => {
    const file = await writeJsonl([
      {
        type: "user",
        uuid: "u1",
        parentUuid: null,
        message: {
          role: "user",
          content: [
            {
              type: "image",
              source: { type: "base64", media_type: "image/png", data: "abc" },
            },
          ],
        },
      },
    ]);
    const before = await fs.readFile(file, "utf8");

    expect(await sanitizeSessionJsonl(file)).toBe(false);
    expect(await fs.readFile(file, "utf8")).toBe(before);
  });

  it("leaves url-sourced images untouched", async () => {
    const file = await writeJsonl([
      {
        type: "user",
        uuid: "u1",
        parentUuid: null,
        message: {
          role: "user",
          content: [
            {
              type: "image",
              source: { type: "url", url: "https://example.com/x.png" },
            },
          ],
        },
      },
    ]);
    const before = await fs.readFile(file, "utf8");

    expect(await sanitizeSessionJsonl(file)).toBe(false);
    expect(await fs.readFile(file, "utf8")).toBe(before);
  });

  it("returns false for missing files", async () => {
    expect(await sanitizeSessionJsonl("/nonexistent/dir/sess.jsonl")).toBe(
      false,
    );
  });
});

describe("hydrateSessionJsonl", () => {
  let configDir: string;
  let originalConfigDir: string | undefined;
  const cwd = "/repo";
  const sessionId = "sess-hydrate";

  beforeEach(async () => {
    originalConfigDir = process.env.CLAUDE_CONFIG_DIR;
    configDir = await fs.mkdtemp(path.join(os.tmpdir(), "jsonl-hydrate-"));
    process.env.CLAUDE_CONFIG_DIR = configDir;
  });

  afterEach(async () => {
    if (originalConfigDir === undefined) delete process.env.CLAUDE_CONFIG_DIR;
    else process.env.CLAUDE_CONFIG_DIR = originalConfigDir;
    await fs
      .chmod(path.dirname(getSessionJsonlPath(sessionId, cwd)), 0o755)
      .catch(() => {});
    await fs.rm(configDir, { recursive: true, force: true });
  });

  async function writeSessionFile(): Promise<string> {
    process.env.CLAUDE_CONFIG_DIR = configDir;
    const file = getSessionJsonlPath(sessionId, cwd);
    await fs.mkdir(path.dirname(file), { recursive: true });
    const poisoned = {
      type: "assistant",
      uuid: "a1",
      parentUuid: null,
      message: {
        role: "assistant",
        content: [
          { type: "text", text: "" },
          { type: "text", text: "hello" },
        ],
      },
    };
    await fs.writeFile(file, `${JSON.stringify(poisoned)}\n`);
    return file;
  }

  function makeDeps() {
    return {
      posthogAPI: { getTaskRun: vi.fn() } as unknown as PostHogAPIClient,
      log: { info: vi.fn(), warn: vi.fn() },
    };
  }

  it("returns the selected conversation when hydrating from logs", async () => {
    const posthogAPI = {
      getTaskRun: vi.fn().mockResolvedValue({ log_url: "https://logs.test" }),
      fetchTaskRunLogs: vi.fn().mockResolvedValue([
        entry("user_message", {
          content: { type: "text", text: "previous request" },
        }),
      ]),
    } as unknown as PostHogAPIClient;
    const log = { info: vi.fn(), warn: vi.fn() };

    const result = await hydrateSessionJsonl({
      sessionId,
      cwd,
      taskId: "t1",
      runId: "r1",
      posthogAPI,
      log,
    });

    expect(result).toEqual({
      hasSession: true,
      conversation: [
        {
          role: "user",
          content: [{ type: "text", text: "previous request" }],
        },
      ],
    });
  });

  it("sanitizes an existing file and skips S3 hydration", async () => {
    const file = await writeSessionFile();
    const { posthogAPI, log } = makeDeps();

    const result = await hydrateSessionJsonl({
      sessionId,
      cwd,
      taskId: "t1",
      runId: "r1",
      posthogAPI,
      log,
    });

    expect(result).toEqual({ hasSession: true });
    expect(
      (posthogAPI as unknown as { getTaskRun: ReturnType<typeof vi.fn> })
        .getTaskRun,
    ).not.toHaveBeenCalled();
    expect(log.info).toHaveBeenCalledWith(
      "Healed existing session JSONL (empty and/or unprocessable-image blocks)",
      expect.anything(),
    );
    expect(await fs.readFile(file, "utf8")).not.toContain('"text":""');
  });

  it("still resumes from the existing file when sanitize cannot write", async () => {
    const file = await writeSessionFile();
    const before = await fs.readFile(file, "utf8");
    await fs.chmod(path.dirname(file), 0o555);
    const { posthogAPI, log } = makeDeps();

    const result = await hydrateSessionJsonl({
      sessionId,
      cwd,
      taskId: "t1",
      runId: "r1",
      posthogAPI,
      log,
    });

    expect(result).toEqual({ hasSession: true });
    expect(log.warn).toHaveBeenCalledWith(
      "Failed to sanitize existing session JSONL",
      expect.anything(),
    );
    expect(
      (posthogAPI as unknown as { getTaskRun: ReturnType<typeof vi.fn> })
        .getTaskRun,
    ).not.toHaveBeenCalled();

    await fs.chmod(path.dirname(file), 0o755);
    expect(await fs.readFile(file, "utf8")).toBe(before);
  });
});
