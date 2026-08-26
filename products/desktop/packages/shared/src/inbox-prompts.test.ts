import { describe, expect, it } from "vitest";

import { normalizeSuggestedPrompts } from "./inbox-prompts";

describe("normalizeSuggestedPrompts", () => {
  it.each([
    ["null", null, []],
    ["undefined", undefined, []],
    ["empty list", [], []],
    ["all blank", ["", "   ", "\n"], []],
    ["trims and drops blanks", [" Why?  ", "", "How?"], ["Why?", "How?"]],
    ["caps at three", ["One", "Two", "Three", "Four"], ["One", "Two", "Three"]],
  ])("returns %s", (_case, input, expected) => {
    expect(normalizeSuggestedPrompts(input)).toEqual(expected);
  });
});
