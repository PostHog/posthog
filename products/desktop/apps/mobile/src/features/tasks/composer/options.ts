import type { ModeInfo } from "@posthog/core/sessions/executionModes";
import {
  type CloudComposerSelection,
  resolveCloudComposerAdapterChange,
} from "@posthog/core/task-detail/composerModelPolicy";
import {
  type Adapter,
  type CloudTaskConfigOption,
  getCapabilityLadder,
  getReasoningEffortOptions,
  isModalModelId,
  isRestrictedModelOption,
  type SupportedReasoningEffort,
} from "@posthog/shared";

export type ContextWindow = "200k" | "1m";
export const DEFAULT_CONTEXT_WINDOW: ContextWindow = "1m";

export interface AgentPreset {
  model: string;
  effort: SupportedReasoningEffort;
  modelLabel: string;
  effortLabel: string;
}

export interface MobileModelOption {
  value: string;
  label: string;
  description?: string;
  disabled: boolean;
}

export function getMobileExecutionModes(
  modes: readonly ModeInfo[],
): ModeInfo[] {
  return modes.filter(
    (mode) => mode.id !== "bypassPermissions" && mode.id !== "full-access",
  );
}

export function getModelConfigOption(
  configOptions: readonly CloudTaskConfigOption[],
): CloudTaskConfigOption {
  const option = configOptions.find((item) => item.category === "model");
  if (!option) throw new Error("Cloud task model configuration is unavailable");
  return option;
}

/**
 * Drops the Kimi K3 model from the live model config when the feature flag is
 * off, and rewrites a persisted or server-default Kimi selection to the first
 * remaining option so it never leaks into the picker. Mirrors the desktop
 * `stripKimiModelOption` filter, but over the mobile `CloudTaskConfigOption`.
 */
export function filterKimiModelOption(
  modelOption: CloudTaskConfigOption,
  kimiEnabled: boolean,
): CloudTaskConfigOption {
  if (kimiEnabled) return modelOption;
  const options = modelOption.options.filter(
    (option) => !isModalModelId(option.value),
  );
  return {
    ...modelOption,
    options,
    currentValue: isModalModelId(modelOption.currentValue)
      ? (options[0]?.value ?? modelOption.currentValue)
      : modelOption.currentValue,
  };
}

/**
 * Applies {@link filterKimiModelOption} to the model option within a live
 * config set, leaving the other categories untouched. Callers filter once at
 * the source so the model auto-resolve effect and the picker share Kimi-free
 * options.
 */
export function filterKimiModelConfigOptions(
  configOptions: readonly CloudTaskConfigOption[],
  kimiEnabled: boolean,
): readonly CloudTaskConfigOption[] {
  if (kimiEnabled) return configOptions;
  return configOptions.map((option) =>
    option.category === "model" ? filterKimiModelOption(option, false) : option,
  );
}

export function getComposerModelOptions(
  modelOption: CloudTaskConfigOption,
): MobileModelOption[] {
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

/**
 * The Faster → Smarter preset scale for the merged model + reasoning control,
 * derived from the shared capability ladder. A notch survives only when its
 * model is present and unrestricted in the live config and its effort is
 * supported for that model, so the scale never offers an unusable pairing.
 */
export function getAgentPresets(
  adapter: Adapter,
  modelOption: CloudTaskConfigOption,
): AgentPreset[] {
  return getCapabilityLadder(adapter).flatMap((notch) => {
    const entry = modelOption.options.find((o) => o.value === notch.model);
    if (!entry || isRestrictedModelOption(entry._meta)) return [];
    const effortOption = getReasoningEffortOptions(adapter, notch.model)?.find(
      (option) => option.value === notch.effort,
    );
    if (!effortOption) return [];
    return [
      {
        model: notch.model,
        effort: notch.effort,
        modelLabel: entry.name,
        effortLabel: effortOption.name,
      },
    ];
  });
}

/** Index of the balanced middle notch on a Faster→Smarter ordered scale. */
function middleIndex(length: number): number {
  return Math.floor((length - 1) / 2);
}

/** The balanced middle notch used as the reset target and harness default. */
export function getMiddlePreset(
  presets: readonly AgentPreset[],
): AgentPreset | undefined {
  if (presets.length === 0) return undefined;
  return presets[middleIndex(presets.length)];
}

/**
 * Switches to the other harness, landing on that harness's middle-notch model
 * and effort rather than a bare default. The composer re-resolves the model
 * against the live config once it loads if this pairing isn't offered yet.
 */
export function resolveHarnessSwitchSelection(
  currentAdapter: Adapter,
): CloudComposerSelection {
  const base = resolveCloudComposerAdapterChange(currentAdapter);
  const ladder = getCapabilityLadder(base.adapter);
  const middle = ladder[middleIndex(ladder.length)];
  if (!middle) return base;
  return { ...base, model: middle.model, reasoning: middle.effort };
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
  if (isRecording) return "mic-stop";
  if (canStop && (!allowSendWhileRunning || !hasContent)) return "stop";
  return hasContent ? "send" : "mic";
}
