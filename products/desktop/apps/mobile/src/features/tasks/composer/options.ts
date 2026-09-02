import {
  getDefaultExecutionModeForAdapter,
  type ModeInfo,
} from "@posthog/core/sessions/executionModes";
import type { CloudComposerSelection } from "@posthog/core/task-detail/composerModelPolicy";
import {
  type Adapter,
  adapterForModelId,
  type CloudTaskConfigOption,
  type CloudTaskConfigSelectGroup,
  DEFAULT_REASONING_EFFORT,
  getCapabilityLadder,
  getReasoningEffortOptions,
  isRestrictedModelOption,
  type SupportedReasoningEffort,
  selectOptionHarness,
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

export interface MobileModelGroup {
  key: string;
  name: string;
  options: MobileModelOption[];
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

function toMobileModelOption(option: {
  value: string;
  name: string;
  description?: string;
  _meta?: Record<string, unknown>;
}): MobileModelOption {
  return {
    value: option.value,
    label: option.name,
    description: option.description,
    disabled: isRestrictedModelOption(option._meta),
  };
}

export function toMobileModelGroups(
  groups: readonly CloudTaskConfigSelectGroup[],
): MobileModelGroup[] {
  return groups.map((group) => ({
    key: group.group,
    name: group.name,
    options: group.options.map(toMobileModelOption),
  }));
}

export function findModelOptionInGroups(
  groups: readonly CloudTaskConfigSelectGroup[],
  value: string,
):
  | { value: string; name: string; _meta?: Record<string, unknown> }
  | undefined {
  for (const group of groups) {
    const entry = group.options.find((option) => option.value === value);
    if (entry) return entry;
  }
  return undefined;
}

export function harnessForModel(
  groups: readonly CloudTaskConfigSelectGroup[],
  value: string,
): Adapter {
  const entry = findModelOptionInGroups(groups, value);
  return selectOptionHarness(entry?._meta) ?? adapterForModelId(value);
}

/**
 * The composer selection for a cross-harness model pick: switches to the
 * picked model's harness, lands on that harness's default mode and reasoning
 * effort, and carries the picked model along.
 */
export function resolveCrossHarnessModelSelection(
  adapter: Adapter,
  model: string,
): CloudComposerSelection {
  return {
    adapter,
    mode: getDefaultExecutionModeForAdapter(adapter),
    model,
    reasoning: DEFAULT_REASONING_EFFORT,
  };
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

function middleIndex(length: number): number {
  return Math.floor((length - 1) / 2);
}

export function getMiddlePreset(
  presets: readonly AgentPreset[],
): AgentPreset | undefined {
  if (presets.length === 0) return undefined;
  return presets[middleIndex(presets.length)];
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
