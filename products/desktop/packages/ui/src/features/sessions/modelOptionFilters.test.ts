import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { describe, expect, it } from "vitest";
import {
  type ModelRolloutFlags,
  stripDisabledModelOption,
  stripDisabledModels,
} from "./modelOptionFilters";

describe("modelOptionFilters", () => {
  const rolloutModels: {
    flag: keyof ModelRolloutFlags;
    id: string;
    name: string;
  }[] = [
    {
      flag: "deepseek",
      id: "deepseek-ai/deepseek-v4-flash-0731",
      name: "DeepSeek V4 Flash",
    },
    { flag: "glm", id: "@cf/zai-org/glm-5.2", name: "GLM-5.2" },
    { flag: "glm53", id: "zai-org/glm-5.3", name: "GLM-5.3" },
    { flag: "glm53Flash", id: "zai-org/glm-5.3-flash", name: "GLM-5.3 Flash" },
    { flag: "kimi", id: "moonshotai/kimi-k3", name: "Kimi K3" },
  ];
  const enabledFlags: ModelRolloutFlags = {
    deepseek: true,
    glm: true,
    glm53: true,
    glm53Flash: true,
    kimi: true,
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
