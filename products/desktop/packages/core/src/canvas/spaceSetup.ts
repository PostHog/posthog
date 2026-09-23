import type {
  SpaceGoalDirection,
  SpaceGoalPeriod,
  SpaceSetupInput,
  SpaceSetupKind,
} from "@posthog/shared/domain-types";

/** What the create-space flow asks the space to be set up for. */
export type SpaceSetupChoice = "none" | SpaceSetupKind;

/** The form fields behind the goal and feature steps, before any trimming. */
export interface SpaceSetupDraft {
  choice: SpaceSetupChoice;
  goal: {
    statement: string;
    target: string;
    direction: SpaceGoalDirection;
    period: SpaceGoalPeriod;
    /** YYYY-MM-DD from a date input, or "". */
    deadline: string;
  };
  feature: {
    name: string;
    flagKey: string;
    description: string;
  };
}

export function emptySpaceSetupDraft(): SpaceSetupDraft {
  return {
    choice: "none",
    goal: {
      statement: "",
      target: "",
      direction: "at_least",
      period: "week",
      deadline: "",
    },
    feature: { name: "", flagKey: "", description: "" },
  };
}

/**
 * The field a setup cannot start without, or null when the draft is complete.
 * A "none" choice is always complete: the space is created without setup.
 */
export function spaceSetupDraftMissingField(
  draft: SpaceSetupDraft,
): "statement" | "name" | null {
  if (draft.choice === "goal" && !draft.goal.statement.trim()) {
    return "statement";
  }
  if (draft.choice === "feature" && !draft.feature.name.trim()) return "name";
  return null;
}

/** A goal setup needs a repository, because its loops open pull requests. */
export function spaceSetupNeedsRepository(draft: SpaceSetupDraft): boolean {
  return draft.choice === "goal";
}

const blankToNull = (value: string): string | null => value.trim() || null;

/** The request body for `POST task_channels/{id}/setup/`, or null for "none". */
export function spaceSetupDraftToInput(
  draft: SpaceSetupDraft,
  repository: string | null,
): SpaceSetupInput | null {
  if (draft.choice === "none") return null;
  if (draft.choice === "goal") {
    return {
      kind: "goal",
      goal: {
        statement: draft.goal.statement.trim(),
        target: blankToNull(draft.goal.target),
        direction: draft.goal.direction,
        period: draft.goal.period,
        deadline: blankToNull(draft.goal.deadline),
      },
      repository,
    };
  }
  return {
    kind: "feature",
    feature: {
      name: draft.feature.name.trim(),
      flag_key: blankToNull(draft.feature.flagKey),
      description: draft.feature.description.trim(),
    },
    repository,
  };
}
