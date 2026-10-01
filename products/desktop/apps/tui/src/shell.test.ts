import { describe, expect, it } from "vitest";
import { parseShell } from "./shell";

describe("parseShell", () => {
  it.each([
    ["!ls -la", "ls -la"],
    ["  ! git status  ", "git status"],
    ["!", null],
    ["!   ", null],
    ["hello !ls", null],
    ["/model", null],
  ])("reads %j", (text, expected) => {
    expect(parseShell(text)).toBe(expected);
  });
});
