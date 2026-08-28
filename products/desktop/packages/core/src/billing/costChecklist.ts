import type { Adapter } from "@posthog/shared";
import { getCapabilityLadder } from "@posthog/shared";
import { modelCostMultiplier } from "./modelPricing";

/**
 * The Cost management checklist.
 *
 * An item exists because there is a change to make, and its button makes it.
 * Whether it reads as a suggestion or as a check is derived from the current
 * setup, not from a stored record of the button having been clicked. Acting on
 * an item moves it out of the active list and into the checked records below.
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

/**
 * A default model at or above this per-token multiple of the baseline earns
 * a "move down a notch" recommendation. 2.5× is the Opus-class rate, the
 * lowest tier where the everyday-task premium is large enough to point out.
 */
const MODEL_NOTCH_TRIGGER_MULTIPLIER = 2.5;

export interface ModelNotchSuggestion {
  fromModelId: string;
  toModelId: string;
}

function adapterForModel(modelId: string): Adapter {
  return modelId.toLowerCase().includes("gpt") ? "codex" : "claude";
}

/**
 * The next capability notch down from the user's default model: the most
 * capable model on the adapter's ladder with a strictly lower per-token
 * multiplier. Null when the default is unset, unpriced, already below the
 * trigger, or nothing on the ladder is cheaper, so the suggestion is always
 * derived from the ladder and always strictly cheaper.
 */
export function modelNotchSuggestion(
  defaultModelId: string | null,
): ModelNotchSuggestion | null {
  if (!defaultModelId) return null;
  const currentMultiplier = modelCostMultiplier(defaultModelId);
  if (
    currentMultiplier === null ||
    currentMultiplier < MODEL_NOTCH_TRIGGER_MULTIPLIER
  ) {
    return null;
  }
  const ladder = getCapabilityLadder(adapterForModel(defaultModelId));
  const models = [...new Set(ladder.map((notch) => notch.model))];
  for (let index = models.length - 1; index >= 0; index--) {
    const model = models[index];
    if (model === undefined) continue;
    const multiplier = modelCostMultiplier(model);
    if (multiplier !== null && multiplier < currentMultiplier) {
      return { fromModelId: defaultModelId, toModelId: model };
    }
  }
  return null;
}

export interface CostChecklistInput {
  /** The model new sessions start on, or null when the user has not picked one. */
  defaultModelId: string | null;
  /**
   * True when a ready custom image exists, false when custom images are
   * available but none is ready, null when they are unavailable or not yet
   * loaded. Null omits the row rather than advertising a build the user
   * cannot start.
   */
  hasCustomImage: boolean | null;
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
 * item appears only when its trigger fires or when it was completed.
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

  // A completed model-notch reads as a checked row only while the current
  // default no longer warrants a cheaper model. Picking an expensive model
  // again — which every composer picker does — re-fires the suggestion instead
  // of leaving a stale checked row that claims a move that no longer holds.
  const notchSuggestion = modelNotchSuggestion(defaultModelId);
  if (isDone("model-notch") && !notchSuggestion) {
    if (defaultModelId) {
      finished.push({
        kind: "model-notch",
        done: true,
        modelId: defaultModelId,
      });
    }
  } else if (notchSuggestion) {
    active.push({ kind: "model-notch", done: false, ...notchSuggestion });
  }

  // The image itself is the record, so this row reads the account rather than
  // a stored completion: a build that was started and then failed or deleted
  // leaves nothing behind, and the recommendation comes back. Null means the
  // account is not known yet or custom images are off, so no row is shown.
  if (hasCustomImage === true) {
    finished.push({ kind: "custom-image", done: true });
  } else if (hasCustomImage === false) {
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
