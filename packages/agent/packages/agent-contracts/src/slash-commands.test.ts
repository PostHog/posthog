import { describe, expect, it } from "vitest";
import { leadingSlashCommand } from "./slash-commands";

describe("leadingSlashCommand", () => {
  it.each([
    ["/clear", "/clear"],
    ["/clear keep the branch", "/clear"],
    ["/clear\nsecond line", "/clear"],
    ["/clearcache", "/clearcache"],
    ["/clear,", "/clear,"],
    ["", undefined],
    [undefined, undefined],
    ["not a command", undefined],
    [" /clear", undefined],
  ])("reads %j as %j", (text, expected) => {
    expect(leadingSlashCommand(text)).toBe(expected);
  });
});
