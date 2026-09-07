import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import {
  isDeepseekModelId,
  isGlm53FlashModelId,
  isGlm53ModelId,
  isGlmModelId,
  isSelectGroup,
} from "@posthog/shared";

const isKimiModelId = (modelId: string): boolean =>
  modelId === "moonshotai/kimi-k3";

export interface ModelRolloutFlags {
  deepseek: boolean;
  glm: boolean;
  glm53: boolean;
  glm53Flash: boolean;
  kimi: boolean;
}

function isModelDisabled(modelId: string, flags: ModelRolloutFlags): boolean {
  return (
    (!flags.deepseek && isDeepseekModelId(modelId)) ||
    (!flags.glm53 && isGlm53ModelId(modelId)) ||
    (!flags.glm53Flash && isGlm53FlashModelId(modelId)) ||
    (!flags.glm &&
      isGlmModelId(modelId) &&
      !isGlm53ModelId(modelId) &&
      !isGlm53FlashModelId(modelId)) ||
    (!flags.kimi && isKimiModelId(modelId))
  );
}

function stripModelOptions(
  option: SessionConfigOption,
  isStripped: (value: string) => boolean,
): SessionConfigOption {
  if (option.type !== "select") return option;

  if (isSelectGroup(option.options)) {
    // A group emptied by the filter must go with its models, or the picker
    // renders a heading with no rows under it.
    const options = option.options
      .map((group) => ({
        ...group,
        options: group.options.filter((model) => !isStripped(model.value)),
      }))
      .filter((group) => group.options.length > 0);
    return {
      ...option,
      options,
      currentValue: isStripped(option.currentValue)
        ? (options.flatMap((group) => group.options)[0]?.value ?? "")
        : option.currentValue,
    };
  }

  const options = option.options.filter((model) => !isStripped(model.value));
  return {
    ...option,
    options,
    currentValue: isStripped(option.currentValue)
      ? (options[0]?.value ?? "")
      : option.currentValue,
  };
}

export function stripDisabledModelOption(
  option: SessionConfigOption,
  flags: ModelRolloutFlags,
): SessionConfigOption {
  return stripModelOptions(option, (modelId) =>
    isModelDisabled(modelId, flags),
  );
}

export function stripDisabledModels<T extends { id: string }>(
  models: T[],
  flags: ModelRolloutFlags,
): T[] {
  return models.filter((model) => !isModelDisabled(model.id, flags));
}
