import { describe, expect, it } from "vitest";
import {
  formatModelRates,
  modelCostInfo,
  modelListPrice,
  relativeCostLabel,
} from "./modelPricing";

describe("modelPricing", () => {
  it.each([
    // The baseline anchors the scale; an exact ratio carries no ≈; diverging
    // input/output ratios earn one; sub-1 multipliers keep two decimals.
    ["claude-sonnet-5", "1×"],
    ["claude-opus-5", "2.5×"],
    ["gpt-5.5", "≈2.8×"],
    ["deepseek-v4", "≈0.05×"],
  ] as const)("%s -> %s", (modelId, expected) => {
    expect(modelCostInfo(modelId)?.multiplierLabel).toBe(expected);
  });

  it("returns null for unknown models so no wrong chip ever renders", () => {
    expect(modelCostInfo("totally-unknown-model")).toBeNull();
    expect(modelListPrice("totally-unknown-model")).toBeNull();
  });

  it("matches specific families before the broader ones they contain", () => {
    expect(modelListPrice("gpt-5.6-luna")?.inputPerMtok).toBe(1);
    expect(modelListPrice("gpt-5.5")?.inputPerMtok).toBe(5);
    expect(modelListPrice("claude-sonnet-4-5")?.inputPerMtok).toBe(3);
    expect(modelListPrice("claude-sonnet-5")?.inputPerMtok).toBe(2);
  });

  it("formats exact rates for tooltips", () => {
    // A sub-dollar rate exercises the two-decimal formatting branch.
    const price = modelListPrice("deepseek-v4");
    expect(price && formatModelRates(price)).toBe(
      "Input $0.13 · Output $0.26 per 1M tokens",
    );
  });

  it("compares two models for the switch dialog", () => {
    expect(relativeCostLabel("claude-opus-5", "claude-haiku-4-5")).toBe("0.2×");
    expect(relativeCostLabel("claude-haiku-4-5", "claude-fable-5")).toBe("10×");
    expect(relativeCostLabel("claude-opus-5", "claude-opus-4-8")).toBeNull();
    expect(relativeCostLabel("claude-opus-5", "unknown-model")).toBeNull();
  });
});

// The gateway pins the contract rates these three families bill at, and this
// table claims to mirror them. In the monorepo the gateway file is six
// directories up; a standalone desktop checkout skips the comparison.
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
    ["kimi", "KIMI_K3_COST"],
    ["glm", "BASETEN_GLM_COST"],
    ["deepseek", "BASETEN_DEEPSEEK_COST"],
    ["fable", "claude-fable-5"],
    ["gpt-5.6-sol", "gpt-5.6-sol"],
    ["gpt-5.6-terra", "gpt-5.6-terra"],
    ["gpt-5.6-luna", "gpt-5.6-luna"],
  ] as const)("%s", async (family, block) => {
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
    const price = modelListPrice(family);
    const input = gatewayRate(gateway, block, "input_cost_per_token");
    const output = gatewayRate(gateway, block, "output_cost_per_token");
    expect(input).not.toBeNull();
    expect(output).not.toBeNull();
    expect(price?.inputPerMtok).toBeCloseTo((input ?? 0) * 1e6, 6);
    expect(price?.outputPerMtok).toBeCloseTo((output ?? 0) * 1e6, 6);
  });
});
