import { describe, expect, it } from "vitest";
import { singleLineTitle } from "./title-text";

describe("singleLineTitle", () => {
  it.each([
    [
      "why did <https://example.com/runs/1?a=b|this run> fail?",
      "why did this run fail?",
    ],
    ["see <https://example.com/runs/1>", "see https://example.com/runs/1"],
    ["read [the report](https://example.com/r.md)", "read the report"],
    [
      'why is it stuck? ```{\n  "id": "1"\n}```',
      'why is it stuck? { "id": "1" }',
    ],
    ["fix `useSearchRows`\n\nsecond line", "fix useSearchRows second line"],
    ["  spaced   out  ", "spaced out"],
  ])("reads %j as one line", (raw, expected) => {
    expect(singleLineTitle(raw)).toBe(expected);
  });
});
