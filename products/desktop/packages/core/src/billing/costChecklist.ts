import { modelNotchSuggestion } from "./costRecommendations";

/**
 * The Cost management checklist.
 *
 * An item exists because there is a change to make, and its button makes it.
 * Whether it reads as a suggestion or as a check comes from the setup itself,
 * never from a record of having once clicked the button. Acting is the only
 * way an item leaves the active list, after which it stays as a checked
 * record at the bottom.
 */

export type CostChecklistItemKind =
  | "model-notch"
  | "custom-image"
  | "install-skill";

export type CostChecklistItem =
  | {
      kind: "model-notch";
      done: false;
      fromModelId: string;
      toModelId: string;
    }
  | { kind: "model-notch"; done: true; modelId: string }
  | { kind: "custom-image"; done: boolean }
  | { kind: "install-skill"; done: boolean; skillId: string; name: string };

export interface CostChecklistInput {
  /** The model new sessions start on, or null when the user has not picked one. */
  defaultModelId: string | null;
  /** True when the user has at least one custom image worth starting from. */
  hasCustomImage: boolean;
  /**
   * Every skill worth a row, in ranked order, each already resolved to
   * whether it is present locally.
   */
  skills: readonly { skillId: string; name: string; installed: boolean }[];
  /** Item kinds the user has already acted on, which stay as checked records. */
  completed: readonly CostChecklistItemKind[];
}

/**
 * Builds the list in reading order: what to do now, then what was done. An
 * item appears when its trigger fires or when it was completed, never
 * otherwise.
 */
export function buildCostChecklist({
  defaultModelId,
  hasCustomImage,
  skills,
  completed,
}: CostChecklistInput): CostChecklistItem[] {
  const isDone = (kind: CostChecklistItemKind) => completed.includes(kind);
  const active: CostChecklistItem[] = [];
  const finished: CostChecklistItem[] = [];

  // A completed item keeps its row even though its trigger has gone quiet —
  // switching the default is precisely what stops the suggestion firing.
  if (isDone("model-notch")) {
    if (defaultModelId) {
      finished.push({
        kind: "model-notch",
        done: true,
        modelId: defaultModelId,
      });
    }
  } else {
    const suggestion = modelNotchSuggestion(defaultModelId);
    if (suggestion) {
      active.push({
        kind: "model-notch",
        done: false,
        fromModelId: suggestion.fromModelId,
        toModelId: suggestion.toModelId,
      });
    }
  }

  // The image itself is the record, so this row reads the account rather than
  // a stored completion: a build that was started and then failed or deleted
  // leaves nothing behind, and the recommendation comes back.
  if (hasCustomImage) {
    finished.push({ kind: "custom-image", done: true });
  } else {
    active.push({ kind: "custom-image", done: false });
  }

  // Installing is its own record, so these rows follow the skill list rather
  // than a stored completion. An installed one stays as a checked row so it
  // can be uninstalled from the same place it was added.
  for (const skill of skills) {
    if (skill.installed) {
      finished.push({
        kind: "install-skill",
        done: true,
        skillId: skill.skillId,
        name: skill.name,
      });
    } else {
      active.push({
        kind: "install-skill",
        done: false,
        skillId: skill.skillId,
        name: skill.name,
      });
    }
  }

  return [...active, ...finished];
}
