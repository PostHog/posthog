import { describe, expect, it } from "vitest";
import { fileExtensionLabel } from "./fileKind";

describe("fileExtensionLabel", () => {
  it.each([
    ["notes.md", ".md"],
    ["NOTES.MD", ".md"],
    ["a.test.ts", ".ts"],
    ["clipboard.png", ".png"],
    [".env", null],
    ["Makefile", null],
    ["trailing.", null],
  ])("labels %s as %s", (filename, expected) => {
    expect(fileExtensionLabel(filename)).toBe(expected);
  });
});
