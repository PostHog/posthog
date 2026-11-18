import { describe, expect, it } from "vitest";
import {
  isRailDestinationActive,
  type RailState,
  stepRailDestination,
  visibleRailDestinations,
} from "./railDestinations";

const order = visibleRailDestinations({
  home: true,
  inbox: true,
  loops: false,
  context: false,
  savedSearches: false,
});
const first = order[0]?.pane;
const last = order[order.length - 1]?.pane;

function state(overrides: Partial<RailState>): RailState {
  return {
    railPane: "home",
    workLayout: false,
    workActivityOpen: false,
    ...overrides,
  };
}

describe("rail destinations", () => {
  it.each([
    ["down from the last wraps to the first", last, 1, first],
    ["up from the first wraps to the last", first, -1, last],
  ] as const)("steps %s", (_, from, direction, expected) => {
    expect(
      stepRailDestination(order, state({ railPane: from }), direction)?.pane,
    ).toBe(expected);
  });

  // Loops is hidden in this order, so on its screen nothing is lit.
  it.each([
    [1, first],
    [-1, last],
  ] as const)("with nothing lit, %i lands on %s", (direction, expected) => {
    expect(
      stepRailDestination(order, state({ railPane: "loops" }), direction)?.pane,
    ).toBe(expected);
  });

  it("lights only Activity while its Work panel is open over a route", () => {
    const open = state({
      railPane: "command-center",
      workLayout: true,
      workActivityOpen: true,
    });

    expect(isRailDestinationActive("activity", open)).toBe(true);
    expect(isRailDestinationActive("command-center", open)).toBe(false);
  });
});
