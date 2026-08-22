/**
 * Relative per-token cost bucket for a model, from the model families the
 * gateway serves. Ordinal only: 1 is the cheapest bucket, 3 the priciest.
 * Unknown families return null so the picker never shows a wrong marker.
 */
export type ModelPriceTier = 1 | 2 | 3;

const TIER_BY_FAMILY: [family: string, tier: ModelPriceTier][] = [
  ["haiku", 1],
  ["deepseek", 1],
  ["glm", 1],
  ["sonnet", 2],
  ["kimi", 2],
  ["opus", 3],
  ["fable", 3],
];

export function modelPriceTier(modelId: string): ModelPriceTier | null {
  const id = modelId.toLowerCase();
  for (const [family, tier] of TIER_BY_FAMILY) {
    if (id.includes(family)) return tier;
  }
  return null;
}

export function modelPriceTierMarker(tier: ModelPriceTier): string {
  return "$".repeat(tier);
}

export function modelPriceTierLabel(tier: ModelPriceTier): string {
  if (tier === 1) return "Lower cost per token";
  if (tier === 2) return "Mid cost per token";
  return "Higher cost per token";
}
