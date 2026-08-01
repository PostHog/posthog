import { describe, expect, it } from "vitest";
import {
  extractCustomInstructions,
  hasCustomInstructions,
} from "./customInstructions";

describe("extractCustomInstructions", () => {
  it("returns null when there is no custom-instructions element", () => {
    expect(extractCustomInstructions("just a normal prompt")).toBeNull();
    expect(hasCustomInstructions("just a normal prompt")).toBe(false);
  });

  it("extracts the body and strips the element from the text", () => {
    const content =
      "Ship the fix\n\n<user_custom_instructions>\nThe user has saved custom instructions that apply to all of their tasks. Follow them.\n\nAlways respond in British English.\n</user_custom_instructions>";
    const result = extractCustomInstructions(content);
    expect(result).not.toBeNull();
    expect(result?.body).toContain("Always respond in British English.");
    expect(result?.stripped).toBe("Ship the fix");
    expect(hasCustomInstructions(content)).toBe(true);
  });

  it("strips the element even when it is the only content", () => {
    const result = extractCustomInstructions(
      "<user_custom_instructions>\nbody\n</user_custom_instructions>",
    );
    expect(result?.body).toBe("body");
    expect(result?.stripped).toBe("");
  });
});
