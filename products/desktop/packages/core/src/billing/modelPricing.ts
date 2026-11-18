import { isCustomModelOption } from "@posthog/shared";
import {
  COST_BASELINE_LABEL,
  COST_BASELINE_MODEL,
  catalogModelFor,
  type ModelCost,
} from "@posthog/shared/model-catalog";

/**
 * Rates and rendered strings both come from the generated catalog, which takes
 * them from products/tasks/backend/model_catalog.py, which pins them against
 * services/llm-gateway/src/llm_gateway/rate_limiting/model_cost_overrides.py.
 * That chain is what makes a price on a chip the price the user is charged.
 */

export type ModelListPrice = ModelCost;

export interface ModelCostInfo {
  price: ModelListPrice;
  /** Per-token cost relative to the baseline, e.g. "0.5×" or "≈1.1×". */
  multiplierLabel: string;
  /** "Input $2 · Output $10 per 1M tokens": the exact rates behind a chip. */
  summary: string;
}

export interface ModelPickerOptionBase {
  value: string;
  name: string;
  _meta?: Record<string, unknown> | null;
}

export interface PricedModelPickerOption extends ModelPickerOptionBase {
  kind: "priced";
  cost: ModelCostInfo;
}

export interface CustomModelPickerOption extends ModelPickerOptionBase {
  kind: "custom";
}

export interface UnpricedModelPickerOption extends ModelPickerOptionBase {
  kind: "unpriced";
}

export type ModelPickerOption =
  | PricedModelPickerOption
  | CustomModelPickerOption
  | UnpricedModelPickerOption;

/** The 1× anchor every multiplier is stated against. */
export const MODEL_COST_BASELINE_NAME = COST_BASELINE_LABEL;

export function modelListPrice(modelId: string): ModelListPrice | null {
  return catalogModelFor(modelId)?.cost ?? null;
}

/**
 * The quantity the catalog renders into `costMultiplier`, as a number, for the
 * callers that rank models by cost instead of naming one.
 */
export function modelCostMultiplier(modelId: string): number | null {
  const price = modelListPrice(modelId);
  const baseline = modelListPrice(COST_BASELINE_MODEL);
  if (!price || !baseline) return null;
  const inputRatio = price.inputPerMtok / baseline.inputPerMtok;
  const outputRatio = price.outputPerMtok / baseline.outputPerMtok;
  return (inputRatio + outputRatio) / 2;
}

export function modelCostInfo(modelId: string): ModelCostInfo | null {
  const model = catalogModelFor(modelId);
  if (!model?.cost || !model.costMultiplier || !model.costSummary) return null;
  return {
    price: model.cost,
    multiplierLabel: model.costMultiplier,
    summary: model.costSummary,
  };
}

/**
 * Converts an ACP model into the picker contract. The pickers call this during
 * render, and the harness names model ids the catalog may not carry, so an
 * unknown id costs the row its cost chip and nothing more.
 */
export function toModelPickerOption(
  model: ModelPickerOptionBase,
): ModelPickerOption {
  if (isCustomModelOption(model._meta)) {
    return { ...model, kind: "custom" };
  }
  const cost = modelCostInfo(model.value);
  if (!cost) {
    return { ...model, kind: "unpriced" };
  }
  return { ...model, kind: "priced", cost };
}

export function estimateUncachedInputCost(
  modelId: string,
  inputTokens: number,
): number | null {
  const price = modelListPrice(modelId);
  if (!price || inputTokens <= 0) return null;
  return (inputTokens / 1_000_000) * price.inputPerMtok;
}
