import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import {
  isDeepseekModelId,
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
  kimi: boolean;
}

function isModelDisabled(modelId: string, flags: ModelRolloutFlags): boolean {
  return (
    (!flags.deepseek && isDeepseekModelId(modelId)) ||
    (!flags.glm53 && isGlm53ModelId(modelId)) ||
    (!flags.glm && isGlmModelId(modelId) && !isGlm53ModelId(modelId)) ||
    (!flags.kimi && isKimiModelId(modelId))
  );
}

function stripModelOptions(
  option: SessionConfigOption,
  isStripped: (value: string) => boolean,
): SessionConfigOption {
  if (option.type !== "select") return option;

  if (isSelectGroup(option.options)) {
    const options = option.options.map((group) => ({
      ...group,
      options: group.options.filter((model) => !isStripped(model.value)),
    }));
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

export function stripGlmModelOption(
  option: SessionConfigOption,
): SessionConfigOption {
  return stripModelOptions(option, isGlmModelId);
}

export function stripDeepseekModelOption(
  option: SessionConfigOption,
): SessionConfigOption {
  return stripModelOptions(option, isDeepseekModelId);
}

export function stripKimiModelOption(
  option: SessionConfigOption,
): SessionConfigOption {
  return stripModelOptions(option, isKimiModelId);
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
