import {
  type Adapter,
  type CloudTaskConfigOption,
  DEFAULT_REASONING_EFFORT,
  isRestrictedModelOption,
  isSupportedReasoningEffort,
  type SupportedReasoningEffort,
} from "@posthog/shared";

export interface ComposerModelOption {
  value: string;
  label: string;
  description?: string;
  disabled: boolean;
}

export function getModelConfigOption(
  configOptions: readonly CloudTaskConfigOption[],
): CloudTaskConfigOption {
  const option = configOptions.find((item) => item.category === "model");
  if (!option) throw new Error("Cloud task model configuration is unavailable");
  return option;
}

export function getComposerModelOptions(
  modelOption: CloudTaskConfigOption,
): ComposerModelOption[] {
  return modelOption.options.map((option) => ({
    value: option.value,
    label: option.name,
    description: option.description,
    disabled: isRestrictedModelOption(option._meta),
  }));
}

export function getConfigOptionLabel(
  options: ReadonlyArray<{ value: string; name: string }>,
  value: string | undefined,
): string | undefined {
  return options.find((option) => option.value === value)?.name ?? value;
}

export function resolveAvailableModel(
  modelOption: CloudTaskConfigOption,
  value: string,
): string {
  const selected = modelOption.options.find((option) => option.value === value);
  return selected && !isRestrictedModelOption(selected._meta)
    ? value
    : modelOption.currentValue;
}

export function resolveComposerModelChange({
  adapter,
  modelOption,
  requestedModel,
  reasoning,
}: {
  adapter: Adapter;
  modelOption: CloudTaskConfigOption;
  requestedModel: string;
  reasoning: SupportedReasoningEffort;
}): { model: string; reasoning: SupportedReasoningEffort } {
  const model = resolveAvailableModel(modelOption, requestedModel);
  return {
    model,
    reasoning: isSupportedReasoningEffort(adapter, model, reasoning)
      ? reasoning
      : DEFAULT_REASONING_EFFORT,
  };
}

export type ComposerPrimaryAction =
  | "send"
  | "stop"
  | "mic"
  | "mic-stop"
  | "disabled";

export function resolveComposerPrimaryAction({
  hasContent,
  disabled,
  isRecording,
  isTranscribing,
  canStop,
  allowSendWhileRunning,
}: {
  hasContent: boolean;
  disabled: boolean;
  isRecording: boolean;
  isTranscribing: boolean;
  canStop: boolean;
  allowSendWhileRunning: boolean;
}): ComposerPrimaryAction {
  if (disabled || isTranscribing) return "disabled";
  if (canStop && (!allowSendWhileRunning || !hasContent)) return "stop";
  if (hasContent && !isRecording) return "send";
  return isRecording ? "mic-stop" : "mic";
}
