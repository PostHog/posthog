import { PRODUCT_ENGINEER_PROMPT } from "@posthog/shared/product-engineer-prompt";
import {
  ANSWER_CHARTS_TAGS_PROMPT,
  RICH_OUTPUT_TAGS_PROMPT,
} from "@posthog/shared/rich-output-prompt";
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
  ])("includes surface-specific guidance for %s", (_name, userPrompt) => {
    for (const [interactionOrigin, answerCharts, richOutput, answerOutput] of [
      [undefined, false, true, false],
      [null, false, true, false],
      ["desktop", false, true, false],
      ["desktop", true, true, false],
      ["signal_report", false, true, false],
      ["slack", false, false, false],
      ["posthog_ai", false, false, false],
      ["posthog_ai", true, false, true],
      ["unknown", false, false, false],
    ] as const) {
      const prompt = buildCloudSessionSystemPrompt(
        "Cloud task instructions.",
        userPrompt,
        interactionOrigin,
        { answerCharts },
      );
      const text = typeof prompt === "string" ? prompt : prompt.append;

      expect(text).toContain(PRODUCT_ENGINEER_PROMPT);
      expect(text.includes(RICH_OUTPUT_TAGS_PROMPT)).toBe(richOutput);
      expect(text.includes(ANSWER_CHARTS_TAGS_PROMPT)).toBe(answerOutput);
      expect(text.indexOf(PRODUCT_ENGINEER_PROMPT)).toBeLessThan(
        text.indexOf("Cloud task instructions."),
      );
    }
  });
});
