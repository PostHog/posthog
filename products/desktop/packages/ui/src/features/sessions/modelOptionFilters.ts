import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { isSelectGroup } from "@posthog/shared";
import { accessFlagForModel } from "@posthog/shared/model-catalog";

/** Whether each model access flag is on for this person, keyed by flag. */
export type ModelRolloutFlags = Record<string, boolean>;

// The catalog says which flag a model needs, so a newly gated model is filtered by adding
// its `access_flag` there rather than by adding a predicate and a branch here. A model the
// catalog does not gate is offered to everyone.
function isModelDisabled(modelId: string, flags: ModelRolloutFlags): boolean {
  const flag = accessFlagForModel(modelId);
  return flag !== undefined && !flags[flag];
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
