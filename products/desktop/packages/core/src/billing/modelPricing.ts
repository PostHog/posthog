import { isCustomModelOption } from "@posthog/shared";

/**
 * List prices per 1M tokens for every model the pickers can show, and the
 * relative per-token cost derived from them. One place on the client; keep in
 * sync with the gateway's billing source
 * (services/llm-gateway/src/llm_gateway/rate_limiting/model_cost_overrides.py).
 *
 * Sources, checked 2026-09-07:
 * - Anthropic (Opus, Sonnet, Haiku): platform.claude.com/docs/en/about-claude/pricing
 * - GPT-5.4, GPT-5.5: developers.openai.com/api/docs/pricing
 * - Fable, GPT-5.6, GPT-6 Astra, Kimi K3, GLM, DeepSeek: the gateway's billing rates, what
 *   the user is actually charged (pinned in the file above). The drift test
 *   binds these rows to it.
 */

export interface ModelListPrice {
  inputPerMtok: number;
  outputPerMtok: number;
}

export interface ModelCostInfo {
  price: ModelListPrice;
  /** Per-token cost relative to the baseline, e.g. "0.5×" or "≈1.1×". */
  multiplierLabel: string;
  /** True when input and output ratios diverge and the label is approximate. */
  approximate: boolean;
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
export const MODEL_COST_BASELINE_NAME = "Claude Sonnet 5";
const BASELINE: ModelListPrice = { inputPerMtok: 2, outputPerMtok: 10 };

// Matched by lowercase substring, first hit wins, so keep specific ids
// (gpt-5.6-*, glm-5.3-flash, sonnet-4) ahead of their broader families.
const LIST_PRICES: [family: string, price: ModelListPrice][] = [
  ["fable", { inputPerMtok: 10, outputPerMtok: 50 }],
  ["mythos", { inputPerMtok: 10, outputPerMtok: 50 }],
  ["opus", { inputPerMtok: 5, outputPerMtok: 25 }],
  ["sonnet-4", { inputPerMtok: 3, outputPerMtok: 15 }],
  ["sonnet", { inputPerMtok: 2, outputPerMtok: 10 }],
  ["haiku", { inputPerMtok: 1, outputPerMtok: 5 }],
  ["gpt-6-astra", { inputPerMtok: 10, outputPerMtok: 50 }],
  ["gpt-5.6-sol", { inputPerMtok: 5, outputPerMtok: 30 }],
  ["gpt-5.6-terra", { inputPerMtok: 2.5, outputPerMtok: 15 }],
  ["gpt-5.6-luna", { inputPerMtok: 1, outputPerMtok: 6 }],
  ["gpt-5.5", { inputPerMtok: 5, outputPerMtok: 30 }],
  ["gpt-5.4", { inputPerMtok: 2.5, outputPerMtok: 15 }],
  ["kimi", { inputPerMtok: 3, outputPerMtok: 15 }],
  ["glm-5.3-flash", { inputPerMtok: 0.15, outputPerMtok: 0.5 }],
  ["glm", { inputPerMtok: 1.4, outputPerMtok: 4.4 }],
  ["deepseek", { inputPerMtok: 0.13, outputPerMtok: 0.26 }],
];

export function modelListPrice(modelId: string): ModelListPrice | null {
  const id = modelId.toLowerCase();
  for (const [family, price] of LIST_PRICES) {
    if (id.includes(family)) return price;
  }
  return null;
}

/** "$4" for whole dollars, "$0.20" otherwise. */
function formatPerMtok(amount: number): string {
  if (Number.isInteger(amount)) return `$${amount}`;
  return `$${amount.toFixed(2)}`;
}

/** "Input $2 · Output $10 per 1M tokens": the exact rates behind a chip. */
export function formatModelRates(price: ModelListPrice): string {
  return `Input ${formatPerMtok(price.inputPerMtok)} · Output ${formatPerMtok(price.outputPerMtok)} per 1M tokens`;
}

function formatMultiplier(value: number, approximate: boolean): string {
  let rounded: string;
  if (value >= 10) {
    rounded = String(Math.round(value));
  } else if (value >= 0.95) {
    const oneDecimal = Math.round(value * 10) / 10;
    rounded = Number.isInteger(oneDecimal)
      ? String(oneDecimal)
      : oneDecimal.toFixed(1);
  } else {
    const twoDecimals = Math.round(value * 100) / 100;
    rounded = String(twoDecimals);
  }
  return `${approximate ? "≈" : ""}${rounded}×`;
}

/**
 * Mean of the input and output rate ratios between two prices, flagged
 * approximate when the two ratios diverge by more than 10%.
 */
function blendedRatio(
  numerator: ModelListPrice,
  denominator: ModelListPrice,
): { blended: number; approximate: boolean } {
  const inputRatio = numerator.inputPerMtok / denominator.inputPerMtok;
  const outputRatio = numerator.outputPerMtok / denominator.outputPerMtok;
  const approximate =
    Math.abs(inputRatio - outputRatio) / Math.max(inputRatio, outputRatio) >
    0.1;
  return { blended: (inputRatio + outputRatio) / 2, approximate };
}

/** Blended per-token multiplier vs the baseline, e.g. 2.5. Null when unpriced. */
export function modelCostMultiplier(modelId: string): number | null {
  const price = modelListPrice(modelId);
  if (!price) return null;
  return blendedRatio(price, BASELINE).blended;
}

export function modelCostInfo(modelId: string): ModelCostInfo | null {
  const price = modelListPrice(modelId);
  if (!price) return null;
  const { blended, approximate } = blendedRatio(price, BASELINE);
  return {
    price,
    multiplierLabel: formatMultiplier(blended, approximate),
    approximate,
  };
}

/**
 * Converts an ACP model into the picker contract. The pickers call this during
 * render, and the harness names model ids this table may not hold, so an
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
