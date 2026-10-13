import { describe, expect, it } from "vitest";
import { buildSideQuestionPrompt } from "./side-question";

describe("buildSideQuestionPrompt", () => {
  it("wraps the question in the side-question constraints", () => {
    const prompt = buildSideQuestionPrompt("what does this function do?");

    expect(prompt).toMatch(
      /^<system-reminder>[\s\S]*<\/system-reminder>\n\nwhat does this function do\?$/,
    );
    expect(prompt).toContain("no tools available");
    expect(prompt).toContain("one-off response");
    expect(prompt).toContain("Never promise actions");
  });
});
