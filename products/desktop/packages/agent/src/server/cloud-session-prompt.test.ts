import { PRODUCT_ENGINEER_PROMPT } from "@posthog/shared/product-engineer-prompt";
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
  ])("includes surface-specific guidance for %s", (_name, userPrompt) => {
    for (const [interactionOrigin, richOutput] of [
      [undefined, true],
      [null, true],
      ["desktop", true],
      ["signal_report", true],
      ["slack", false],
      ["posthog_ai", false],
      ["unknown", false],
    ] as const) {
      const prompt = buildCloudSessionSystemPrompt(
        "Cloud task instructions.",
        userPrompt,
        interactionOrigin,
      );
      const text = typeof prompt === "string" ? prompt : prompt.append;

      expect(text).toContain(PRODUCT_ENGINEER_PROMPT);
      expect(text.includes(RICH_OUTPUT_TAGS_PROMPT)).toBe(richOutput);
      expect(text.indexOf(PRODUCT_ENGINEER_PROMPT)).toBeLessThan(
        text.indexOf("Cloud task instructions."),
      );
    }
  });
});
