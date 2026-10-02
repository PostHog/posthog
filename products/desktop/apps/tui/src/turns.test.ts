import { describe, expect, it } from "vitest";
import { noTurns, reportTurn, type TurnState, visit } from "./turns";

const sets = (state: TurnState): { working: string[]; waiting: string[] } => ({
  working: [...state.working.values()],
  waiting: [...state.waiting],
});

// One pane's reports in order: the chat it shows, whether that chat is mid-turn, and whether the pane has focus.
const after = (
  reports: [taskId: string | null, working: boolean, focused: boolean][],
): TurnState =>
  reports.reduce(
    (state, [taskId, working, focused]) =>
      reportTurn(state, "p1", taskId, working, focused),
    noTurns,
  );

describe("reportTurn", () => {
  it.each([
    ["a chat mid-turn works", [["a", true, false]], ["a"], []],
    [
      "a turn that ends away from the reader waits for them",
      [
        ["a", true, false],
        ["a", false, false],
      ],
      [],
      ["a"],
    ],
    [
      "a turn that ends in front of the reader does not",
      [
        ["a", true, true],
        ["a", false, true],
      ],
      [],
      [],
    ],
    [
      "a new turn stops the wait",
      [
        ["a", true, false],
        ["a", false, false],
        ["a", true, false],
      ],
      ["a"],
      [],
    ],
    [
      "a pane that moves to another chat leaves nothing waiting",
      [
        ["a", true, false],
        ["b", false, false],
      ],
      [],
      [],
    ],
  ] as const)("%s", (_, reports, working, waiting) => {
    expect(sets(after(reports.map((report) => [...report])))).toEqual({
      working,
      waiting,
    });
  });

  it("keeps the same state when nothing changed, so a report on every render settles", () => {
    const state = after([["a", true, false]]);
    expect(reportTurn(state, "p1", "a", true, false)).toBe(state);
  });

  it("stops waiting once the reader visits the chat", () => {
    const state = after([
      ["a", true, false],
      ["a", false, false],
    ]);
    expect(sets(visit(state, "a")).waiting).toEqual([]);
    expect(visit(noTurns, "a")).toBe(noTurns);
  });
});
