import { describe, expect, it } from "vitest";

import {
  cachedDiffStats,
  extractCloudFileContent,
  extractCloudToolChangedFiles,
  type ParsedToolCall,
} from "./cloudToolChanges";

function diffObj(
  newText: string,
  oldText: string,
): NonNullable<Parameters<typeof cachedDiffStats>[0]> {
  return { type: "diff", path: "src/f.ts", newText, oldText };
}

function toolCall(overrides: Partial<ParsedToolCall>): ParsedToolCall {
  return {
    toolCallId: overrides.toolCallId ?? "tc-1",
    kind: overrides.kind ?? null,
    title: overrides.title,
    status: overrides.status ?? "completed",
    locations: overrides.locations,
    content: overrides.content,
    rawOutput: overrides.rawOutput,
  };
}

function textContent(text: string): ParsedToolCall["content"] {
  return [{ type: "content", content: { type: "text", text } }];
}

function diffContent(
  path: string,
  newText: string,
  oldText?: string,
): ParsedToolCall["content"] {
  return [{ type: "diff", path, newText, oldText: oldText ?? null }];
}

function makeToolCalls(
  ...calls: ParsedToolCall[]
): Map<string, ParsedToolCall> {
  return new Map(calls.map((tc, i) => [tc.toolCallId || `tc-${i}`, tc]));
}

describe("extractCloudToolChangedFiles", () => {
  it("excludes plan files from changed files", () => {
    const calls = makeToolCalls(
      toolCall({
        toolCallId: "tc-plan",
        kind: "write",
        locations: [
          {
            path: "/home/user/.claude/plans/breezy-squishing-twilight.md",
          },
        ],
        content: diffContent(
          "/home/user/.claude/plans/breezy-squishing-twilight.md",
          "# Plan\n\nDo stuff",
        ),
      }),
      toolCall({
        toolCallId: "tc-real",
        kind: "edit",
        locations: [{ path: "src/app.ts" }],
        content: diffContent("src/app.ts", "new code", "old code"),
      }),
    );
    const result = extractCloudToolChangedFiles(calls);
    expect(result).toHaveLength(1);
    expect(result[0].path).toBe("src/app.ts");
  });

  it.each([
    {
      name: "new file counts all lines as added",
      kind: "write" as const,
      oldText: undefined,
      newText: "a\nb\nc",
      added: 3,
      removed: 0,
    },
    {
      name: "modified file counts added and removed",
      kind: "edit" as const,
      oldText: "a\nb\nc",
      newText: "a\nB\nc\nd",
      added: 2,
      removed: 1,
    },
    {
      name: "pure removal counts removed only",
      kind: "edit" as const,
      oldText: "a\nb\nc",
      newText: "a",
      added: 0,
      removed: 2,
    },
  ])("diff stats: $name", ({ kind, oldText, newText, added, removed }) => {
    const calls = makeToolCalls(
      toolCall({
        toolCallId: "tc",
        kind,
        locations: [{ path: "src/f.ts" }],
        content: diffContent("src/f.ts", newText, oldText),
      }),
    );
    const [file] = extractCloudToolChangedFiles(calls);
    expect(file.linesAdded).toBe(added);
    expect(file.linesRemoved).toBe(removed);
  });

  it("leaves line counts undefined for image/video files", () => {
    const calls = makeToolCalls(
      toolCall({
        toolCallId: "tc-img",
        kind: "write",
        locations: [{ path: "assets/logo.png" }],
        content: diffContent("assets/logo.png", "a\nb\nc\nd\ne"),
      }),
    );
    const [file] = extractCloudToolChangedFiles(calls);
    expect(file.path).toBe("assets/logo.png");
    expect(file.linesAdded).toBeUndefined();
    expect(file.linesRemoved).toBeUndefined();
  });

  it("memoizes diff stats by diff-object identity", () => {
    const diff = diffObj("a\nB\nc", "a\nb\nc");
    const first = cachedDiffStats(diff);
    expect(cachedDiffStats(diff)).toBe(first);

    const distinctButEqual = diffObj("a\nB\nc", "a\nb\nc");
    const recomputed = cachedDiffStats(distinctButEqual);
    expect(recomputed).not.toBe(first);
    expect(recomputed).toEqual(first);
  });
});

describe("extractCloudFileContent", () => {
  it("returns untouched for an empty tool calls map", () => {
    const result = extractCloudFileContent(new Map(), "src/app.ts");
    expect(result).toEqual({ content: null, touched: false });
  });

  it("returns untouched when no tool call matches the file", () => {
    const calls = makeToolCalls(
      toolCall({
        kind: "read",
        locations: [{ path: "src/other.ts" }],
        content: textContent("other content"),
      }),
    );
    const result = extractCloudFileContent(calls, "src/app.ts");
    expect(result).toEqual({ content: null, touched: false });
  });

  it("extracts content from a read tool call", () => {
    const calls = makeToolCalls(
      toolCall({
        kind: "read",
        locations: [{ path: "src/app.ts" }],
        content: textContent("file content"),
      }),
    );
    const result = extractCloudFileContent(calls, "src/app.ts");
    expect(result).toEqual({ content: "file content", touched: true });
  });

  it("extracts content from a write tool call", () => {
    const calls = makeToolCalls(
      toolCall({
        kind: "write",
        locations: [{ path: "src/app.ts" }],
        content: diffContent("src/app.ts", "new content"),
      }),
    );
    const result = extractCloudFileContent(calls, "src/app.ts");
    expect(result).toEqual({ content: "new content", touched: true });
  });

  it("extracts content from an edit tool call", () => {
    const calls = makeToolCalls(
      toolCall({
        kind: "edit",
        locations: [{ path: "src/app.ts" }],
        content: diffContent("src/app.ts", "edited content", "old content"),
      }),
    );
    const result = extractCloudFileContent(calls, "src/app.ts");
    expect(result).toEqual({ content: "edited content", touched: true });
  });

  // A file_unchanged read carries Claude Code's "Wasted call ..." dedup
  // sentinel instead of the file body, so it must never be treated as content.
  const fileUnchangedRead = (id: string): ParsedToolCall =>
    toolCall({
      toolCallId: id,
      kind: "read",
      locations: [{ path: "src/app.ts" }],
      rawOutput: { type: "file_unchanged" },
      content: textContent(
        "```\nWasted call — file unchanged since your last Read. Refer to that earlier tool_result instead.\n```",
      ),
    });

  it.each([
    {
      name: "read alone yields no content (dedup sentinel not shown)",
      calls: [fileUnchangedRead("tc-unchanged")],
      expected: { content: null, touched: false },
    },
    {
      name: "read after a real read keeps the real content",
      calls: [
        toolCall({
          toolCallId: "tc-read",
          kind: "read",
          locations: [{ path: "src/app.ts" }],
          content: textContent("real content"),
        }),
        fileUnchangedRead("tc-unchanged"),
      ],
      expected: { content: "real content", touched: true },
    },
    {
      name: "read after a write keeps the written content",
      calls: [
        toolCall({
          toolCallId: "tc-write",
          kind: "write",
          locations: [{ path: "src/app.ts" }],
          content: diffContent("src/app.ts", "written content"),
        }),
        fileUnchangedRead("tc-unchanged"),
      ],
      expected: { content: "written content", touched: true },
    },
  ])("file_unchanged $name", ({ calls, expected }) => {
    const result = extractCloudFileContent(
      makeToolCalls(...calls),
      "src/app.ts",
    );
    expect(result).toEqual(expected);
  });

  it("marks deleted files as touched with null content", () => {
    const calls = makeToolCalls(
      toolCall({
        toolCallId: "tc-read",
        kind: "read",
        locations: [{ path: "src/app.ts" }],
        content: textContent("original"),
      }),
      toolCall({
        toolCallId: "tc-delete",
        kind: "delete",
        locations: [{ path: "src/app.ts" }],
      }),
    );
    const result = extractCloudFileContent(calls, "src/app.ts");
    expect(result).toEqual({ content: null, touched: true });
  });

  it("uses the latest content when multiple tool calls touch the same file", () => {
    const calls = makeToolCalls(
      toolCall({
        toolCallId: "tc-read",
        kind: "read",
        locations: [{ path: "src/app.ts" }],
        content: textContent("v1"),
      }),
      toolCall({
        toolCallId: "tc-edit",
        kind: "edit",
        locations: [{ path: "src/app.ts" }],
        content: diffContent("src/app.ts", "v2", "v1"),
      }),
    );
    const result = extractCloudFileContent(calls, "src/app.ts");
    expect(result).toEqual({ content: "v2", touched: true });
  });

  it("skips failed tool calls", () => {
    const calls = makeToolCalls(
      toolCall({
        kind: "write",
        status: "failed",
        locations: [{ path: "src/app.ts" }],
        content: diffContent("src/app.ts", "bad content"),
      }),
    );
    const result = extractCloudFileContent(calls, "src/app.ts");
    expect(result).toEqual({ content: null, touched: false });
  });

  it("matches absolute paths against relative paths", () => {
    const calls = makeToolCalls(
      toolCall({
        kind: "read",
        locations: [{ path: "/home/user/project/src/app.ts" }],
        content: textContent("absolute match"),
      }),
    );
    const result = extractCloudFileContent(calls, "src/app.ts");
    expect(result).toEqual({ content: "absolute match", touched: true });
  });

  it("infers kind from title when kind is not set", () => {
    const calls = makeToolCalls(
      toolCall({
        kind: null,
        title: "Write src/app.ts",
        locations: [{ path: "src/app.ts" }],
        content: diffContent("src/app.ts", "inferred write"),
      }),
    );
    const result = extractCloudFileContent(calls, "src/app.ts");
    expect(result).toEqual({ content: "inferred write", touched: true });
  });

  describe("move operations", () => {
    it("marks file as touched when looking up the source path", () => {
      const calls = makeToolCalls(
        toolCall({
          kind: "move",
          locations: [{ path: "src/old.ts" }, { path: "src/new.ts" }],
        }),
      );
      const result = extractCloudFileContent(calls, "src/old.ts");
      expect(result).toEqual({ content: null, touched: true });
    });

    it("marks file as touched when looking up the destination path", () => {
      const calls = makeToolCalls(
        toolCall({
          kind: "move",
          locations: [{ path: "src/old.ts" }, { path: "src/new.ts" }],
        }),
      );
      const result = extractCloudFileContent(calls, "src/new.ts");
      expect(result).toEqual({ content: null, touched: true });
    });

    it("extracts content from move with diff", () => {
      const calls = makeToolCalls(
        toolCall({
          kind: "move",
          locations: [{ path: "src/old.ts" }, { path: "src/new.ts" }],
          content: diffContent("src/new.ts", "moved content"),
        }),
      );
      const result = extractCloudFileContent(calls, "src/new.ts");
      expect(result).toEqual({ content: "moved content", touched: true });
    });

    it("does not match unrelated paths for move", () => {
      const calls = makeToolCalls(
        toolCall({
          kind: "move",
          locations: [{ path: "src/old.ts" }, { path: "src/new.ts" }],
        }),
      );
      const result = extractCloudFileContent(calls, "src/other.ts");
      expect(result).toEqual({ content: null, touched: false });
    });
  });
});
