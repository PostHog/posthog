import { beforeEach, describe, expect, it } from "vitest";
import {
  costMultiplierLabel,
  forgetGatewayModels,
  isOfferedModel,
  isRetiredModel,
  labelForModel,
  offeredModelsOf,
  rememberGatewayModels,
  supports1MContext,
  supportsFastMode,
} from "./model-catalog";
import {
  backendOfferedModels,
  rememberSavedGatewayListing,
} from "./testing/saved-gateway-listing";

describe("the gateway listing", () => {
  beforeEach(() => {
    forgetGatewayModels();
  });

  it("offers the models the backend offers the desktop product", () => {
    const offered = rememberSavedGatewayListing().map((model) => model.id);

    expect(offered.sort()).toEqual(backendOfferedModels());
  });

  it.each([
    ["claude-opus-5-5", true],
    ["anthropic/claude-opus-5-5", true],
    ["OPENAI/GPT-6.2-SOL", true],
    ["zai-org/glm-5.3", true],
    ["deepseek-ai/deepseek-v4.1-flash-1017-fast", true],
    ["gpt-6-sol", false],
    ["claude-opus-4-8", false],
    ["gpt-5.4", false],
    ["@cf/zai-org/glm-5.2", false],
    ["claude-haiku-4-5", false],
    ["gpt-5.5-codex", false],
  ])("offers %s: %s", (modelId, expected) => {
    rememberSavedGatewayListing();

    expect(isOfferedModel(modelId)).toBe(expected);
  });

  it.each([
    ["gpt-6-sol", true],
    ["@cf/zai-org/glm-5.2", true],
    ["claude-haiku-4-5", true],
    ["claude-opus-5-5", false],
    ["gpt-5.5-codex", false],
  ])("retires %s: %s", (modelId, expected) => {
    rememberSavedGatewayListing();

    expect(isRetiredModel(modelId)).toBe(expected);
  });

  it("offers every row of a listing that names no families", () => {
    const legacy = [{ id: "claude-opus-4-5" }, { id: "some-new-model" }];

    expect(offeredModelsOf(legacy)).toEqual(legacy);
  });

  it("keeps the last listing when the gateway answers with none", () => {
    rememberSavedGatewayListing();
    rememberGatewayModels([]);

    expect(isOfferedModel("claude-opus-5-5")).toBe(true);
  });

  it.each([
    ["claude-opus-5-5", "Claude Opus 5.5"],
    ["claude-haiku-4-5", "Claude Haiku 4.5"],
    ["deepseek-ai/deepseek-v4-flash-0731", undefined],
    ["gpt-5.5-codex", undefined],
  ])("names %s %s", (modelId, expected) => {
    rememberSavedGatewayListing();

    expect(labelForModel(modelId)).toBe(expected);
  });

  it.each([
    ["claude-opus-5-5", true, true],
    ["claude-sonnet-5-5", true, false],
    ["claude-opus-4-5", false, true],
    ["zai-org/glm-5.3", false, false],
    ["gpt-6.2-sol", false, false],
    ["claude-opus-9", false, false],
  ])(
    "gives %s the 1M window: %s, fast mode: %s",
    (modelId, longContext, fastMode) => {
      rememberSavedGatewayListing();

      expect([supports1MContext(modelId), supportsFastMode(modelId)]).toEqual([
        longContext,
        fastMode,
      ]);
    },
  );
});

describe("costMultiplierLabel", () => {
  it.each([
    [2, 10, "1×"],
    [5, 25, "2.5×"],
    [5, 30, "≈2.8×"],
    [5, 20, "≈2.2×"],
    [0.15, 0.5, "≈0.06×"],
    [30, 150, "15×"],
  ])(
    "reads $%s in and $%s out as %s",
    (inputPerMtok, outputPerMtok, expected) => {
      const baseline = { inputPerMtok: 2, outputPerMtok: 10 };

      expect(
        costMultiplierLabel({ inputPerMtok, outputPerMtok }, baseline),
      ).toBe(expected);
    },
  );
});
