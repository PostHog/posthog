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
  ])("includes shared guidance for %s", (_name, userPrompt) => {
    const prompt = buildCloudSessionSystemPrompt(
      "Cloud task instructions.",
      userPrompt,
    );
    const text = typeof prompt === "string" ? prompt : prompt.append;

    expect(text).toContain(PRODUCT_ENGINEER_PROMPT);
    expect(text).toContain(RICH_OUTPUT_TAGS_PROMPT);
    expect(text.indexOf(PRODUCT_ENGINEER_PROMPT)).toBeLessThan(
      text.indexOf("Cloud task instructions."),
    );
  });

  it.each([
    ["a desktop run", undefined, true],
    ["an inbox report run", "signal_report", true],
    ["a Slack run", "slack", false],
    ["a PostHog AI run", "posthog_ai", false],
  ])(
    "teaches the object-tag vocabulary to %s: %s",
    (_name, interactionOrigin, expected) => {
      const prompt = buildCloudSessionSystemPrompt(
        "Cloud task instructions.",
        undefined,
        interactionOrigin,
      );
      const text = typeof prompt === "string" ? prompt : prompt.append;

      expect(text.includes(RICH_OUTPUT_TAGS_PROMPT)).toBe(expected);
      expect(text).toContain(PRODUCT_ENGINEER_PROMPT);
    },
  );
});
