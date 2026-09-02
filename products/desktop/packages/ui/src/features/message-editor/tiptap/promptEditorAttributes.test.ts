import { describe, expect, it } from "vitest";
import { getPromptEditorAttributes } from "./promptEditorAttributes";

describe("getPromptEditorAttributes", () => {
  it("enables native spell checking", () => {
    expect(getPromptEditorAttributes()).toMatchObject({ spellcheck: "true" });
  });
});
