import { customModelMeta } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  estimateUncachedInputCost,
  modelCostInfo,
  modelCostMultiplier,
  modelListPrice,
  toModelPickerOption,
} from "./modelPricing";

describe("modelPricing", () => {
  it.each([
    // The baseline anchors the scale; an exact ratio carries no ≈; diverging
    // input/output ratios earn one; sub-1 multipliers keep two decimals.
    ["claude-sonnet-5", "1×"],
    ["claude-opus-5", "2.5×"],
    ["gpt-5.5", "≈2.8×"],
    ["gpt-6-astra", "5×"],
    ["deepseek-ai/deepseek-v4-flash-0731", "≈0.05×"],
    ["zai-org/glm-5.3-flash", "≈0.06×"],
    // A picker hands back whichever form the gateway served.
    ["anthropic/claude-opus-5", "2.5×"],
    ["openai/gpt-6-sol", "1×"],
  ] as const)("%s -> %s", (modelId, expected) => {
    expect(modelCostInfo(modelId)?.multiplierLabel).toBe(expected);
  });

  it.each([
    // Absent from the catalog, then in it with no published price.
    "totally-unknown-model",
    "gpt-5",
  ] as const)("%s carries no price, so no wrong chip renders", (modelId) => {
    expect(modelCostInfo(modelId)).toBeNull();
    expect(modelListPrice(modelId)).toBeNull();
  });

  it("keeps an unpriced gateway model in the picker instead of throwing", () => {
    expect(
      toModelPickerOption({
        value: "future-gateway-model",
        name: "Future gateway model",
      }),
    ).toMatchObject({ kind: "unpriced", name: "Future gateway model" });

    expect(
      toModelPickerOption({
        value: "local-model",
        name: "Local model",
        _meta: customModelMeta(),
      }),
    ).toMatchObject({ kind: "custom" });
  });

  it("ranks models by the numeric multiplier the chips state", () => {
    const opus = modelCostMultiplier("claude-opus-5");
    const sonnet = modelCostMultiplier("claude-sonnet-5");
    expect(sonnet).toBe(1);
    expect(opus).toBe(2.5);
    expect(modelCostMultiplier("totally-unknown-model")).toBeNull();
  });

  it("carries the exact rates for tooltips", () => {
    // A sub-dollar rate exercises the two-decimal formatting the catalog does.
    expect(modelCostInfo("deepseek-ai/deepseek-v4-flash-0731")?.summary).toBe(
      "Input $0.13 · Output $0.26 per 1M tokens",
    );
  });

  it.each([
    ["gpt-5.6-terra", 100_000, 0.25],
    ["claude-sonnet-5", 50_000, 0.1],
    ["unknown-model", 100_000, null],
    ["claude-opus-5", 0, null],
  ] as const)(
    "estimates uncached input cost for %s with %s tokens",
    (modelId, tokens, expected) => {
      expect(estimateUncachedInputCost(modelId, tokens)).toBe(expected);
    },
  );
});

// The gateway pins the contract rates these models bill at, and the catalog
// this file reads claims to mirror them. In the monorepo the gateway file is
// six directories up; a standalone desktop checkout skips the comparison.
const MONOREPO_ROOT_RELATIVE = "../../../../../..";
const MONOREPO_SENTINEL_RELATIVE = `${MONOREPO_ROOT_RELATIVE}/pyproject.toml`;
const GATEWAY_OVERRIDES_RELATIVE = `${MONOREPO_ROOT_RELATIVE}/services/llm-gateway/src/llm_gateway/rate_limiting/model_cost_overrides.py`;

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function gatewayRate(
  source: string,
  block: string,
  key: string,
): number | null {
  const b = escapeRegExp(block);
  // The gateway holds rates in two shapes: a top-level `NAME = { ... }`
  // constant (the Baseten/Kimi models) and a quoted `"model-id": { ... }`
  // entry in the overrides dict (Fable and the GPT-5.6 models).
  const blockMatch = source.match(
    new RegExp(`(?:"${b}"\\s*:|${b}[^=\\n]*=)\\s*\\{([\\s\\S]*?)\\}`),
  );
  if (!blockMatch?.[1]) return null;
  const rate = blockMatch[1].match(
    new RegExp(`"${escapeRegExp(key)}":\\s*([0-9][0-9_.e-]*)`),
  );
  return rate?.[1] ? Number(rate[1].replaceAll("_", "")) : null;
}

describe("contract rates match the gateway's pinned table", () => {
  it.each([
    ["moonshotai/kimi-k3", "KIMI_K3_COST"],
    ["zai-org/glm-5.3", "BASETEN_GLM_COST"],
    ["zai-org/glm-5.3-flash", "BASETEN_GLM53_FLASH_COST"],
    ["deepseek-ai/deepseek-v4-flash-0731", "BASETEN_DEEPSEEK_COST"],
    ["claude-fable-5", "claude-fable-5"],
    ["gpt-5.6-sol", "gpt-5.6-sol"],
    ["gpt-5.6-terra", "gpt-5.6-terra"],
    ["gpt-5.6-luna", "gpt-5.6-luna"],
    ["gpt-6-astra", "gpt-6-astra"],
  ] as const)("%s", async (modelId, block) => {
    // A dynamic import keeps the pure-layer lint honest: only this test
    // touches the filesystem, and only to read the gateway's table.
    const { access, readFile } = await import("node:fs/promises");
    try {
      await access(new URL(MONOREPO_SENTINEL_RELATIVE, import.meta.url));
    } catch {
      // Not the monorepo, so there is no gateway table to compare against.
      return;
    }
    // In the monorepo the gateway file must exist: a read failure here means
    // it moved, and the mirror claim above needs its path updated.
    const gateway = await readFile(
      new URL(GATEWAY_OVERRIDES_RELATIVE, import.meta.url),
      "utf-8",
    );
    const price = modelListPrice(modelId);
    const input = gatewayRate(gateway, block, "input_cost_per_token");
    const output = gatewayRate(gateway, block, "output_cost_per_token");
    expect(input).not.toBeNull();
    expect(output).not.toBeNull();
    expect(price?.inputPerMtok).toBeCloseTo((input ?? 0) * 1e6, 6);
    expect(price?.outputPerMtok).toBeCloseTo((output ?? 0) * 1e6, 6);
  });
});
