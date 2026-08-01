import { describe, expect, it } from "vitest";
import { renderTranscriptMarkdown, truncateForModel } from "./format";
import type { SingleRunResult } from "./run-agent";

function baseResult(overrides: Partial<SingleRunResult> = {}): SingleRunResult {
  return {
    runId: "run-abc",
    startedAt: Date.now(),
    agent: "scout",
    task: "find the auth code",
    exitCode: 0,
    messages: [],
    stderr: "",
    usage: {
      input: 10,
      output: 20,
      cacheRead: 0,
      cacheWrite: 0,
      cost: 0.02,
      contextTokens: 30,
      turns: 1,
    },
    model: "anthropic/opus",
    ...overrides,
  };
}

describe("truncateForModel", () => {
  it("passes short output through unchanged", () => {
    expect(truncateForModel("short", 100)).toBe("short");
  });

  it("truncates and reports omitted byte count", () => {
    const result = truncateForModel("x".repeat(200), 50);
    expect(result.length).toBeLessThan(250);
    expect(result).toMatch(/Output truncated: \d+ bytes omitted/);
  });
});

describe("renderTranscriptMarkdown", () => {
  it("includes header metadata, task, and error section for a failed run", () => {
    const result = baseResult({
      exitCode: 1,
      stopReason: "error",
      errorMessage: "boom",
      stderr: "stack trace",
    });
    const md = renderTranscriptMarkdown(result);
    expect(md).toContain("# Subagent run: scout");
    expect(md).toContain("- runId: run-abc");
    expect(md).toContain("- stopReason: error");
    expect(md).toContain("find the auth code");
    expect(md).toContain("## Error");
    expect(md).toContain("boom");
    expect(md).toContain("## stderr");
    expect(md).toContain("stack trace");
  });

  it("renders assistant text, tool calls, and tool results in order", () => {
    const result = baseResult({
      messages: [
        {
          role: "assistant",
          content: [
            { type: "text", text: "Let me check the file." },
            {
              type: "toolCall",
              id: "1",
              name: "read",
              arguments: { path: "auth.ts" },
            },
          ],
        } as never,
        {
          role: "toolResult",
          toolCallId: "1",
          toolName: "read",
          isError: false,
          content: [{ type: "text", text: "file contents here" }],
        } as never,
      ],
    });

    const md = renderTranscriptMarkdown(result);
    const textIdx = md.indexOf("Let me check the file.");
    const callIdx = md.indexOf("Tool call: `read`");
    const resultIdx = md.indexOf("Tool result: `read`");
    expect(textIdx).toBeGreaterThanOrEqual(0);
    expect(callIdx).toBeGreaterThan(textIdx);
    expect(resultIdx).toBeGreaterThan(callIdx);
    expect(md).toContain('"path": "auth.ts"');
    expect(md).toContain("file contents here");
  });

  it("marks a failed tool result distinctly", () => {
    const result = baseResult({
      messages: [
        {
          role: "toolResult",
          toolCallId: "1",
          toolName: "bash",
          isError: true,
          content: [{ type: "text", text: "command not found" }],
        } as never,
      ],
    });
    expect(renderTranscriptMarkdown(result)).toContain(
      "Tool result (error): `bash`",
    );
  });
});
