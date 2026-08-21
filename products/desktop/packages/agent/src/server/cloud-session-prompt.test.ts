import { RICH_OUTPUT_TAGS_PROMPT } from "@posthog/shared/rich-output-prompt";
import { describe, expect, it } from "vitest";
import { buildCloudSessionSystemPrompt } from "./agent-server";

describe("buildCloudSessionSystemPrompt", () => {
  it.each([
    ["the default prompt", undefined],
    ["a string override", "Answer in JSON."],
    [
      "a preset override",
      {
        type: "preset" as const,
        preset: "claude_code" as const,
        append: "Use the canvas tools.",
      },
    ],
  ])("includes rich-output instructions for %s", (_name, userPrompt) => {
    const prompt = buildCloudSessionSystemPrompt(
      "Cloud task instructions.",
      userPrompt,
    );
    const text = typeof prompt === "string" ? prompt : prompt.append;

    expect(text).toContain(RICH_OUTPUT_TAGS_PROMPT);
  });
});
