import { describe, expect, it } from "vitest";
import { collapsePiSkillInvocation } from "./piSkillInvocation";

describe("collapsePiSkillInvocation", () => {
  it("replaces Pi skill instructions with the command and user request", () => {
    expect(
      collapsePiSkillInvocation(
        '<skill name="code-review" location="/skills/code-review/SKILL.md">\nReferences are relative to /skills/code-review.\n\n# Review\n\nInspect the diff.\n</skill>\n\nReview this pull request.',
      ),
    ).toBe("/code-review\n\nReview this pull request.");
  });

  it("keeps non-skill messages unchanged", () => {
    expect(collapsePiSkillInvocation("Review this pull request.")).toBe(
      "Review this pull request.",
    );
  });
});
