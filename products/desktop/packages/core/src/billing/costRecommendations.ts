import type { Adapter } from "@posthog/shared";
import { getCapabilityLadder } from "@posthog/shared";
import { modelCostMultiplier } from "./modelPricing";

/**
 * A default model at or above this per-token multiple of the baseline earns
 * a "move down a notch" recommendation. 2.5× is the Opus-class rate, the
 * lowest tier where the everyday-task premium is large enough to point out.
 */
export const MODEL_NOTCH_TRIGGER_MULTIPLIER = 2.5;

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
 * trigger, or nothing on the ladder is cheaper — a suggestion is never
 * hardcoded and never sideways.
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
