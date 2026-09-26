import { describe, expect, it } from "vitest";
import {
  PRODUCT_ENGINEER_PROMPT,
  prependProductEngineerPrompt,
} from "./product-engineer-prompt";

const UPSTREAM_PROMPT = "Existing runtime guidance.";

describe("prependProductEngineerPrompt", () => {
  it.each([
    ["an empty prompt", "", PRODUCT_ENGINEER_PROMPT],
    [
      "existing runtime guidance",
      UPSTREAM_PROMPT,
      `${PRODUCT_ENGINEER_PROMPT}\n\n${UPSTREAM_PROMPT}`,
    ],
  ])(
    "prepends product engineering guidance to %s",
    (_name, prompt, expected) => {
      expect(prependProductEngineerPrompt(prompt)).toBe(expected);
    },
  );

  it("does not duplicate guidance when a session rebuilds its prompt", () => {
    const firstPrompt = prependProductEngineerPrompt(UPSTREAM_PROMPT);

    expect(prependProductEngineerPrompt(firstPrompt)).toBe(firstPrompt);
  });
});
