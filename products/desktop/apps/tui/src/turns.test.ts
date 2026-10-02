import { describe, expect, it } from "vitest";
import { noTurns, settle, type TurnState, visit } from "./turns";

// One chat's reports in order: whether it is mid-turn, and whether the reader is on it.
const after = (reports: [working: boolean, seen: boolean][]): TurnState =>
  reports.reduce(
    (state, [working, seen]) => settle(state, "a", working, seen),
    noTurns,
  );

describe("settle", () => {
  it.each([
    ["a chat mid-turn works", [[true, false]], true, false],
    [
      "a turn that ends away from the reader waits for them",
      [
        [true, false],
        [false, false],
      ],
      false,
      true,
    ],
    [
      "a turn that ends in front of the reader does not",
      [
        [true, true],
        [false, true],
      ],
      false,
      false,
    ],
    [
      "a new turn stops the wait",
      [
        [true, false],
        [false, false],
        [true, false],
      ],
      true,
      false,
    ],
    [
      "a chat that was never mid-turn does not wait",
      [[false, false]],
      false,
      false,
    ],
  ] as const)("%s", (_, reports, working, waiting) => {
    const state = after(reports.map((report) => [...report]));
    expect([state.working.has("a"), state.waiting.has("a")]).toEqual([
      working,
      waiting,
    ]);
  });

  it("keeps the same state when nothing changed, so repeated reports settle", () => {
    const state = after([[true, false]]);
    expect(settle(state, "a", true, false)).toBe(state);
  });

  it("stops waiting once the reader visits the chat", () => {
    const state = after([
      [true, false],
      [false, false],
    ]);
    expect(visit(state, "a").waiting.has("a")).toBe(false);
    expect(visit(noTurns, "a")).toBe(noTurns);
  });
});
