import { describe, expect, it } from "vitest";
import { type AutoConvertedPaste, isRepeatOfAutoConvertedPaste } from "./paste";

const lastPaste: AutoConvertedPaste = {
  clipboardText: "https://github.com/posthog/code/issues/42",
  insertText: "https://github.com/posthog/code/issues/42",
  chipId: "chip-1",
};

describe("isRepeatOfAutoConvertedPaste", () => {
  it.each([
    {
      name: "same clipboard text as the last conversion",
      last: lastPaste,
      clipboardText: lastPaste.clipboardText,
      expected: true,
    },
    {
      name: "no prior conversion",
      last: null,
      clipboardText: lastPaste.clipboardText,
      expected: false,
    },
    {
      name: "different clipboard text",
      last: lastPaste,
      clipboardText: "something else",
      expected: false,
    },
    {
      name: "clipboard text differing only by whitespace",
      last: lastPaste,
      clipboardText: `${lastPaste.clipboardText} `,
      expected: false,
    },
    {
      name: "empty clipboard text",
      last: lastPaste,
      clipboardText: "",
      expected: false,
    },
    {
      name: "undefined clipboard text",
      last: lastPaste,
      clipboardText: undefined,
      expected: false,
    },
  ])("returns $expected for $name", ({ last, clipboardText, expected }) => {
    expect(isRepeatOfAutoConvertedPaste(last, clipboardText)).toBe(expected);
  });
});
