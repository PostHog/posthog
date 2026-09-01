import type { PrReviewComment } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  buildAskAboutPrCommentPrompt,
  buildBatchedInlineCommentsPrompt,
  buildChatAboutPrCommentPrompt,
  buildFixPrCommentPrompt,
  buildInlineCommentPrompt,
} from "./reviewPrompts";
import type { DraftComment } from "./types";

function makeDraft(overrides: Partial<DraftComment> = {}): DraftComment {
  return {
    id: "d1",
    taskId: "t1",
    filePath: "src/a.ts",
    startLine: 10,
    endLine: 10,
    side: "additions",
    text: "fix this",
    createdAt: 0,
    ...overrides,
  };
}

function makeComment(body: string, login = "alice"): PrReviewComment {
  return { user: { login }, body } as PrReviewComment;
}

describe("buildInlineCommentPrompt", () => {
  it("escapes the file path and renders a single line ref", () => {
    const out = buildInlineCommentPrompt('a"&<>.ts', 5, 5, "deletions", "hi");
    expect(out).toContain("&quot;");
    expect(out).toContain("&amp;");
    expect(out).toContain("line 5");
    expect(out).toContain("(old)");
  });

  it("renders a range and new side", () => {
    const out = buildInlineCommentPrompt("a.ts", 3, 7, "additions", "hi");
    expect(out).toContain("lines 3-7");
    expect(out).toContain("(new)");
  });
});

describe("buildBatchedInlineCommentsPrompt", () => {
  it("returns empty for no drafts", () => {
    expect(buildBatchedInlineCommentsPrompt([])).toBe("");
  });

  it("delegates to the single-comment prompt for one draft", () => {
    const out = buildBatchedInlineCommentsPrompt([makeDraft()]);
    expect(out).toBe(
      buildInlineCommentPrompt("src/a.ts", 10, 10, "additions", "fix this"),
    );
  });

  it("renders a bulleted, indented list for multiple drafts", () => {
    const out = buildBatchedInlineCommentsPrompt([
      makeDraft({ id: "d1", text: "one" }),
      makeDraft({ id: "d2", filePath: "b.ts", text: "two\nlines" }),
    ]);
    expect(out).toContain("Please address these review comments:");
    expect(out).toContain("- In file");
    expect(out).toContain("  lines");
  });
});

describe("PR comment prompts", () => {
  it("includes the thread body and side", () => {
    const out = buildFixPrCommentPrompt("a.ts", 4, "new", [
      makeComment("please rename"),
    ]);
    expect(out).toContain("line 4 (new)");
    expect(out).toContain("@alice");
    expect(out).toContain("please rename");
  });

  it("ask prompt asks for understanding without changes", () => {
    const out = buildAskAboutPrCommentPrompt("a.ts", 4, "old", [
      makeComment("why?"),
    ]);
    expect(out).toContain("Do not make any changes");
  });

  it("chat prompt includes the thread and custom message", () => {
    const out = buildChatAboutPrCommentPrompt(
      'src/a".ts',
      8,
      "new",
      [makeComment("consider extracting this", "reviewer")],
      "Is there already a helper for this?",
    );
    expect(out).toContain('<file path="src/a&quot;.ts" />');
    expect(out).toContain("line 8 (new)");
    expect(out).toContain("@reviewer");
    expect(out).toContain("consider extracting this");
    expect(out.endsWith("Is there already a helper for this?")).toBe(true);
  });
});
