import { describe, expect, it } from "vitest";
import {
  buildAutoContext,
  composeTaskWithContext,
  resolveContext,
} from "./context";

function makeCtx(
  entries: Array<{
    type: string;
    message?: { role: string; content: Array<{ type: string; text?: string }> };
  }>,
) {
  return {
    sessionManager: { getBranch: () => entries },
  } as unknown as Parameters<typeof buildAutoContext>[0];
}

describe("buildAutoContext", () => {
  it("returns an empty string for a fresh session with no messages", () => {
    expect(buildAutoContext(makeCtx([]))).toBe("");
  });

  it("extracts text from user/assistant messages, oldest first", () => {
    const ctx = makeCtx([
      {
        type: "message",
        message: {
          role: "user",
          content: [{ type: "text", text: "find the bug" }],
        },
      },
      {
        type: "message",
        message: {
          role: "assistant",
          content: [{ type: "text", text: "found it in auth.ts" }],
        },
      },
    ]);
    const digest = buildAutoContext(ctx);
    expect(digest).toBe("User: find the bug\n\nAssistant: found it in auth.ts");
  });

  it("skips non-message entries and tool-only messages with no text", () => {
    const ctx = makeCtx([
      { type: "thinking_level_change" },
      {
        type: "message",
        message: {
          role: "toolResult",
          content: [{ type: "text", text: "ignored: not user/assistant" }],
        },
      },
      {
        type: "message",
        message: { role: "assistant", content: [{ type: "toolCall" }] },
      },
      {
        type: "message",
        message: { role: "user", content: [{ type: "text", text: "kept" }] },
      },
    ]);
    expect(buildAutoContext(ctx)).toBe("User: kept");
  });

  it("caps to maxMessages, keeping the most recent turns", () => {
    const entries = Array.from({ length: 10 }, (_, i) => ({
      type: "message",
      message: {
        role: "user" as const,
        content: [{ type: "text", text: `turn-${i}` }],
      },
    }));
    const digest = buildAutoContext(makeCtx(entries), { maxMessages: 2 });
    expect(digest).toBe("User: turn-8\n\nUser: turn-9");
  });

  it("caps to maxChars, truncating from the front", () => {
    const ctx = makeCtx([
      {
        type: "message",
        message: {
          role: "user",
          content: [{ type: "text", text: "x".repeat(100) }],
        },
      },
    ]);
    const digest = buildAutoContext(ctx, { maxChars: 20 });
    expect(digest.length).toBeLessThanOrEqual(
      20 + "\n\n[earlier context truncated]".length,
    );
    expect(digest).toMatch(/^\[earlier context truncated\]/);
  });
});

describe("resolveContext", () => {
  it("prefers explicit context over the auto digest", () => {
    const ctx = makeCtx([
      {
        type: "message",
        message: { role: "user", content: [{ type: "text", text: "auto" }] },
      },
    ]);
    expect(resolveContext(ctx, "explicit")).toBe("explicit");
  });

  it("trims explicit context", () => {
    const ctx = makeCtx([]);
    expect(resolveContext(ctx, "  padded  ")).toBe("padded");
  });

  it("falls back to auto context when explicit is empty/whitespace/undefined", () => {
    const ctx = makeCtx([
      {
        type: "message",
        message: { role: "user", content: [{ type: "text", text: "auto" }] },
      },
    ]);
    expect(resolveContext(ctx, undefined)).toBe("User: auto");
    expect(resolveContext(ctx, "   ")).toBe("User: auto");
  });
});

describe("composeTaskWithContext", () => {
  it("returns just the task when there's no context", () => {
    expect(composeTaskWithContext("do the thing", "")).toBe(
      "Task: do the thing",
    );
  });

  it("appends a context section when context is present", () => {
    const composed = composeTaskWithContext("do the thing", "some context");
    expect(composed).toBe(
      "Task: do the thing\n\nContext from the orchestrating session:\nsome context",
    );
  });
});
