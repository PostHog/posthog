import { describe, expect, it } from "vitest";
import { appendRichOutputPrompt } from "./rich-output-prompt";

describe("appendRichOutputPrompt", () => {
  it.each(["slack", "posthog_ai", "unknown"])(
    "removes existing rich-output guidance for %s",
    (interactionOrigin) => {
      const basePrompt = "Answer clearly.";
      const desktopPrompt = appendRichOutputPrompt(basePrompt);

      expect(appendRichOutputPrompt(desktopPrompt, interactionOrigin)).toBe(
        basePrompt,
      );
      expect(appendRichOutputPrompt(basePrompt, interactionOrigin)).toBe(
        basePrompt,
      );
      expect(appendRichOutputPrompt(desktopPrompt, "desktop")).toBe(
        desktopPrompt,
      );
    },
  );
});
