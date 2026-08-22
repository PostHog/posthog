import { modelNotchSuggestion } from "./costRecommendations";

/**
 * The Cost management checklist.
 *
 * Three rules the shape enforces. Every item is actionable: it exists because
 * there is a change to make, and its button makes it. Every item is
 * conditional: an item that would appear identically for everyone is not a
 * recommendation, so it never enters the list. And nothing is dismissible:
 * acting is the only way an item leaves the active list, after which it stays
 * as a checked record at the bottom.
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
  | { kind: "custom-image"; done: false; repository: string }
  | { kind: "custom-image"; done: true; repository: string }
  | { kind: "install-skill"; done: boolean; skillId: string; name: string };

export interface CostChecklistInput {
  /** The model new sessions start on, or null when the user has not picked one. */
  defaultModelId: string | null;
  /** The repository the user's last cloud run used, or null if they have none. */
  cloudRepository: string | null;
  /** True when that repository's cloud runs already start from a custom image. */
  cloudRepositoryHasCustomImage: boolean;
  /**
   * True once the person has spend to reduce. Setup advice waits for it, so a
   * brand-new account is not handed a list of chores.
   */
  hasSpendHistory: boolean;
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
  cloudRepository,
  cloudRepositoryHasCustomImage,
  hasSpendHistory,
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

  if (cloudRepository) {
    if (isDone("custom-image")) {
      finished.push({
        kind: "custom-image",
        done: true,
        repository: cloudRepository,
      });
    } else if (!cloudRepositoryHasCustomImage) {
      active.push({
        kind: "custom-image",
        done: false,
        repository: cloudRepository,
      });
    }
  }

  // Installing is its own record, so these rows follow the skill list rather
  // than a stored completion. An installed one stays as a checked row so it
  // can be removed from the same place it was added.
  for (const skill of skills) {
    if (skill.installed) {
      finished.push({
        kind: "install-skill",
        done: true,
        skillId: skill.skillId,
        name: skill.name,
      });
    } else if (hasSpendHistory) {
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
