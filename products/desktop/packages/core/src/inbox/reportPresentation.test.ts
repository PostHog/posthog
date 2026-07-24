import { describe, expect, it } from "vitest";
import {
  deriveHeadline,
  displayConventionalCommitTitle,
  formatSignalReportSummaryMarkdown,
  parseConventionalCommitTitle,
} from "./reportPresentation";

describe("deriveHeadline", () => {
  it("returns null for null/undefined/empty input", () => {
    expect(deriveHeadline(null)).toBeNull();
    expect(deriveHeadline(undefined)).toBeNull();
    expect(deriveHeadline("")).toBeNull();
    expect(deriveHeadline("   ")).toBeNull();
  });

  it("returns the only sentence when there's just one", () => {
    expect(deriveHeadline("Single short sentence with no terminator")).toBe(
      "Single short sentence with no terminator",
    );
    expect(deriveHeadline("Single short sentence.")).toBe(
      "Single short sentence.",
    );
  });

  it("keeps only the first sentence of a multi-sentence summary", () => {
    expect(
      deriveHeadline(
        "First sentence here. Second sentence follows. And a third.",
      ),
    ).toBe("First sentence here.");
  });

  it("handles `!` and `?` terminators", () => {
    expect(deriveHeadline("Surprise! That's the headline.")).toBe("Surprise!");
    expect(deriveHeadline("Is this the headline? Yes.")).toBe(
      "Is this the headline?",
    );
  });

  it("cuts at the first newline before considering further sentences", () => {
    expect(deriveHeadline("First line headline\nSecond paragraph here.")).toBe(
      "First line headline",
    );
  });

  it("strips trailing Markdown emphasis at the sentence boundary", () => {
    expect(deriveHeadline("**Bold headline.** Then prose.")).toBe(
      "Bold headline.",
    );
    expect(deriveHeadline("_Italic._ Continuation.")).toBe("Italic.");
    expect(deriveHeadline("`code-led headline.` Plain after.")).toBe(
      "code-led headline.",
    );
  });

  it("truncates long single sentences with an ellipsis", () => {
    const longSentence = `${"a".repeat(160)}`;
    const headline = deriveHeadline(longSentence);
    expect(headline?.endsWith("…")).toBe(true);
    expect(headline?.length).toBeLessThanOrEqual(141);
  });

  it("does not truncate sentences under the limit", () => {
    expect(deriveHeadline("Short enough sentence here.")).toBe(
      "Short enough sentence here.",
    );
  });
});

describe("formatSignalReportSummaryMarkdown", () => {
  it.each([
    {
      name: "puts section body text on a new line after the header",
      input:
        "**What's happening:** Error tracking issue keyed on `app:dashboard_query`.",
      expected:
        "**What's happening:**\n\nError tracking issue keyed on `app:dashboard_query`.",
    },
    {
      name: "separates consecutive section headers onto their own lines",
      input:
        "**What's happening:** Users hit rate limits. **Root cause:** All four rate limiters are contended. **How to resolve:** Reduce blocking.",
      expected:
        "**What's happening:**\n\nUsers hit rate limits.\n\n**Root cause:**\n\nAll four rate limiters are contended.\n\n**How to resolve:**\n\nReduce blocking.",
    },
    {
      name: "separates a section header from preceding intro text",
      input:
        "Users on busy orgs are hitting hard limits. **What's happening:** Error tracking issue.",
      expected:
        "Users on busy orgs are hitting hard limits.\n\n**What's happening:**\n\nError tracking issue.",
    },
    {
      name: "leaves content without section headers unchanged",
      input: "Plain summary with no structured sections.",
      expected: "Plain summary with no structured sections.",
    },
  ])("$name", ({ input, expected }) => {
    expect(formatSignalReportSummaryMarkdown(input)).toBe(expected);
  });
});

describe("parseConventionalCommitTitle", () => {
  it("returns null for empty or non-conventional titles", () => {
    expect(parseConventionalCommitTitle(null)).toBeNull();
    expect(parseConventionalCommitTitle("")).toBeNull();
    expect(parseConventionalCommitTitle("Fix tooltip overflow")).toBeNull();
    expect(parseConventionalCommitTitle("feat:")).toBeNull();
  });

  it("parses type, scope, and description", () => {
    expect(
      parseConventionalCommitTitle("fix(auth): Stop duplicate sessions"),
    ).toEqual({
      type: "fix",
      scope: "auth",
      description: "Stop duplicate sessions",
    });
  });

  it("normalizes type to lowercase", () => {
    expect(parseConventionalCommitTitle("Feat(ui): Add inbox tab")).toEqual({
      type: "feat",
      scope: "ui",
      description: "Add inbox tab",
    });
  });

  it("parses titles without scope", () => {
    expect(parseConventionalCommitTitle("chore: Bump dependencies")).toEqual({
      type: "chore",
      scope: null,
      description: "Bump dependencies",
    });
  });

  it("parses breaking-change markers", () => {
    expect(parseConventionalCommitTitle("feat!: Drop legacy API")).toEqual({
      type: "feat",
      scope: null,
      description: "Drop legacy API",
    });
    expect(
      parseConventionalCommitTitle("fix(api)!: Remove deprecated route"),
    ).toEqual({
      type: "fix",
      scope: "api",
      description: "Remove deprecated route",
    });
  });
});

describe("displayConventionalCommitTitle", () => {
  it("returns description for conventional titles", () => {
    expect(
      displayConventionalCommitTitle(
        "fix(auth): Stop duplicate sessions",
        "Untitled",
      ),
    ).toBe("Stop duplicate sessions");
  });

  it("returns full title or fallback otherwise", () => {
    expect(displayConventionalCommitTitle("Plain title", "Untitled")).toBe(
      "Plain title",
    );
    expect(displayConventionalCommitTitle(null, "Untitled")).toBe("Untitled");
  });
});
