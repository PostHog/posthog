import { describe, expect, it } from "vitest";
import {
  emptySpaceSetupDraft,
  type SpaceSetupDraft,
  spaceSetupDraftMissingField,
  spaceSetupDraftToInput,
} from "./spaceSetup";

function draft(overrides: Partial<SpaceSetupDraft>): SpaceSetupDraft {
  return { ...emptySpaceSetupDraft(), ...overrides };
}

describe("spaceSetup draft", () => {
  it.each([
    ["none is always complete", draft({ choice: "none" }), null],
    [
      "a goal needs a statement",
      draft({
        choice: "goal",
        goal: { ...emptySpaceSetupDraft().goal, statement: "   " },
      }),
      "statement",
    ],
    ["a feature needs a name", draft({ choice: "feature" }), "name"],
  ])("missing field: %s", (_name, value, expected) => {
    expect(spaceSetupDraftMissingField(value)).toBe(expected);
  });

  it("turns a goal draft into the request body with blanks as null", () => {
    const input = spaceSetupDraftToInput(
      draft({
        choice: "goal",
        goal: {
          statement: "  Increase weekly activation  ",
          target: "20%",
          direction: "at_least",
          period: "week",
          deadline: "",
        },
      }),
      "posthog/posthog",
    );

    expect(input).toEqual({
      kind: "goal",
      goal: {
        statement: "Increase weekly activation",
        target: "20%",
        direction: "at_least",
        period: "week",
        deadline: null,
      },
      repository: "posthog/posthog",
    });
  });

  it("turns a feature draft into the request body and none into null", () => {
    expect(
      spaceSetupDraftToInput(
        draft({
          choice: "feature",
          feature: { name: "Checklist", flagKey: "", description: "" },
        }),
        null,
      ),
    ).toEqual({
      kind: "feature",
      feature: { name: "Checklist", flag_key: null, description: "" },
      repository: null,
    });
    expect(spaceSetupDraftToInput(draft({ choice: "none" }), null)).toBeNull();
  });
});
