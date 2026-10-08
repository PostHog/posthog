import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { describe, expect, it, vi } from "vitest";
import {
  type ModelRolloutFlags,
  stripDisabledModelOption,
  stripDisabledModels,
} from "./modelOptionFilters";

const GATED_MODEL = "acme/gated-model";
const GATED_FLAG = "acme-gated-model";

// The catalog gates no model at the moment, so the strip paths need a stand-in to be
// exercised at all. Naming a real model here would instead tie these cases to a rollout
// that ends, which is how the open-weights models stayed hidden after their flags were
// fully rolled out.
vi.mock("@posthog/shared/model-catalog", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@posthog/shared/model-catalog")>();
  return {
    ...actual,
    accessFlagForModel: (modelId: string): string | undefined =>
      modelId === GATED_MODEL ? GATED_FLAG : actual.accessFlagForModel(modelId),
  };
});

describe("modelOptionFilters", () => {
  const openWeightsModels = [
    { id: "deepseek-ai/deepseek-v4-flash-0731", name: "DeepSeek V4 Flash" },
    { id: "@cf/zai-org/glm-5.2", name: "GLM-5.2" },
    { id: "zai-org/glm-5.3", name: "GLM-5.3" },
    { id: "zai-org/glm-5.3-flash", name: "GLM-5.3 Flash" },
    { id: "moonshotai/kimi-k3", name: "Kimi K3" },
  ];
  const noFlags: ModelRolloutFlags = {};

  it.each(openWeightsModels)(
    "offers $name, which the catalog does not gate",
    ({ id, name }) => {
      const option: SessionConfigOption = {
        type: "select",
        id: "model",
        name: "Model",
        currentValue: id,
        options: [
          { value: id, name },
          { value: "claude-opus-4-8", name: "Claude Opus 4.8" },
        ],
      };

      expect(stripDisabledModelOption(option, noFlags)).toEqual(option);
      expect(stripDisabledModels([{ id }], noFlags)).toEqual([{ id }]);
    },
  );

  it("selects an available model when the gated one is not reachable", () => {
    const option: SessionConfigOption = {
      type: "select",
      id: "model",
      name: "Model",
      currentValue: GATED_MODEL,
      options: [
        { value: GATED_MODEL, name: "Gated model" },
        { value: "claude-opus-4-8", name: "Claude Opus 4.8" },
      ],
    };

    expect(
      stripDisabledModelOption(option, { [GATED_FLAG]: false }),
    ).toMatchObject({
      currentValue: "claude-opus-4-8",
      options: [{ value: "claude-opus-4-8" }],
    });
  });

  it("drops a group emptied by a disabled flag, heading and all", () => {
    const option: SessionConfigOption = {
      type: "select",
      id: "model",
      name: "Model",
      currentValue: "claude-opus-5",
      options: [
        {
          group: "anthropic",
          name: "Anthropic",
          options: [{ value: "claude-opus-5", name: "Claude Opus 5" }],
        },
        {
          group: "acme",
          name: "Acme",
          options: [{ value: GATED_MODEL, name: "Gated model" }],
        },
      ],
    };

    expect(
      stripDisabledModelOption(option, { [GATED_FLAG]: false }),
    ).toMatchObject({
      currentValue: "claude-opus-5",
      options: [{ group: "anthropic" }],
    });
  });

  it("removes only the models whose flag is off", () => {
    const models = [
      ...openWeightsModels.map(({ id }) => ({ id })),
      { id: GATED_MODEL },
      { id: "gpt-5.6-terra" },
    ];

    expect(stripDisabledModels(models, { [GATED_FLAG]: false })).toEqual(
      models.filter((model) => model.id !== GATED_MODEL),
    );
  });
});
