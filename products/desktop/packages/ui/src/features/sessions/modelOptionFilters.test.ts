import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import {
  DEEPSEEK_MODEL_FLAG,
  GLM_MODEL_FLAG,
  GLM53_FLASH_MODEL_FLAG,
  GLM53_MODEL_FLAG,
  KIMI_MODEL_FLAG,
} from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  type ModelRolloutFlags,
  stripDisabledModelOption,
  stripDisabledModels,
} from "./modelOptionFilters";

describe("modelOptionFilters", () => {
  // The flag beside each id is the one the catalog records for it, so a case fails if the
  // two ever disagree about which flag gates the model.
  const rolloutModels: { flag: string; id: string; name: string }[] = [
    {
      flag: DEEPSEEK_MODEL_FLAG,
      id: "deepseek-ai/deepseek-v4-flash-0731",
      name: "DeepSeek V4 Flash",
    },
    { flag: GLM_MODEL_FLAG, id: "@cf/zai-org/glm-5.2", name: "GLM-5.2" },
    { flag: GLM53_MODEL_FLAG, id: "zai-org/glm-5.3", name: "GLM-5.3" },
    {
      flag: GLM53_FLASH_MODEL_FLAG,
      id: "zai-org/glm-5.3-flash",
      name: "GLM-5.3 Flash",
    },
    { flag: KIMI_MODEL_FLAG, id: "moonshotai/kimi-k3", name: "Kimi K3" },
  ];
  const enabledFlags: ModelRolloutFlags = {
    [DEEPSEEK_MODEL_FLAG]: true,
    [GLM_MODEL_FLAG]: true,
    [GLM53_MODEL_FLAG]: true,
    [GLM53_FLASH_MODEL_FLAG]: true,
    [KIMI_MODEL_FLAG]: true,
  };

  it.each(rolloutModels)(
    "selects an available model when $flag is disabled",
    ({ flag, id, name }) => {
      const flags = { ...enabledFlags, [flag]: false };
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

      expect(stripDisabledModelOption(option, flags)).toMatchObject({
        currentValue: "claude-opus-4-8",
        options: [{ value: "claude-opus-4-8" }],
      });
    },
  );

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
          group: "moonshotai",
          name: "Moonshot AI",
          options: [{ value: "moonshotai/kimi-k3", name: "Kimi K3" }],
        },
      ],
    };

    expect(
      stripDisabledModelOption(option, {
        ...enabledFlags,
        [KIMI_MODEL_FLAG]: false,
      }),
    ).toMatchObject({
      currentValue: "claude-opus-5",
      options: [{ group: "anthropic" }],
    });
  });

  it.each(rolloutModels)(
    "removes only $flag models when its flag is disabled",
    ({ flag, id }) => {
      const flags = { ...enabledFlags, [flag]: false };
      const models = [
        ...rolloutModels.map(({ id, name }) => ({ id, name })),
        { id: "gpt-5.6-terra", name: "GPT-5.6 Terra" },
      ];

      expect(stripDisabledModels(models, flags)).toEqual(
        models.filter((model) => model.id !== id),
      );
    },
  );
});
