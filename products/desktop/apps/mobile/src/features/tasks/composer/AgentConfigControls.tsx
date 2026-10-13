import { getAvailableModesForAdapter } from "@posthog/core/sessions/executionModes";
import type { CloudComposerSelection } from "@posthog/core/task-detail/composerModelPolicy";
import {
  type Adapter,
  type CloudTaskConfigOption,
  type CloudTaskConfigSelectGroup,
  type ExecutionMode,
  FAST_MODE_FLAG,
  getReasoningEffortOptions,
  type SupportedReasoningEffort,
  supports1MContext,
  supportsFastMode,
} from "@posthog/shared";
import {
  Cpu,
  Lightning,
  PauseIcon,
  PencilIcon,
  Robot,
  ShieldCheck,
  Sparkle,
} from "phosphor-react-native";
import { useFeatureFlag } from "posthog-react-native";
import { type ReactNode, useMemo, useState } from "react";
import { useThemeColors } from "@/lib/theme";
import { AgentConfigSheet } from "./AgentConfigSheet";
import {
  type AgentPreset,
  type ContextWindow,
  DEFAULT_CONTEXT_WINDOW,
  findModelOptionInGroups,
  getAgentPresets,
  getMiddlePreset,
  getMobileExecutionModes,
  getModelConfigOption,
  harnessForModel,
  resolveCrossHarnessModelSelection,
  toMobileModelGroups,
} from "./options";
import { Pill } from "./Pill";
import { SelectSheet } from "./SelectSheet";

interface AgentConfigControlsProps {
  adapter: Adapter;
  mode: ExecutionMode;
  model: string;
  reasoning: SupportedReasoningEffort;
  contextWindow: ContextWindow;
  fastMode: boolean;
  configOptions: readonly CloudTaskConfigOption[];
  modelGroups: readonly CloudTaskConfigSelectGroup[];
  /**
   * Called for both cross-harness picks and manual harness switches. Same
   * shape as the desktop `resolveCloudComposerAdapterChange` result.
   */
  onAdapterChange: (selection: CloudComposerSelection) => void;
  onModeChange: (mode: ExecutionMode) => void;
  onModelChange: (model: string) => void;
  onReasoningChange: (reasoning: SupportedReasoningEffort) => void;
  onContextWindowChange: (contextWindow: ContextWindow) => void;
  onFastModeChange: (enabled: boolean) => void;
  canChangeAdapter?: boolean;
}

function modeIcon(mode: ExecutionMode, color: string, size = 14): ReactNode {
  switch (mode) {
    case "plan":
      return <PauseIcon size={size} color={color} weight="bold" />;
    case "default":
      return <PencilIcon size={size} color={color} />;
    case "acceptEdits":
      return <ShieldCheck size={size} color={color} />;
    case "bypassPermissions":
    case "full-access":
      return <ShieldCheck size={size} color={color} weight="fill" />;
    case "read-only":
      return <PauseIcon size={size} color={color} />;
    case "auto":
      return <Sparkle size={size} color={color} weight="fill" />;
  }
}

export function AgentConfigControls({
  adapter,
  mode,
  model,
  reasoning,
  contextWindow,
  fastMode,
  configOptions,
  modelGroups,
  onAdapterChange,
  onModeChange,
  onModelChange,
  onReasoningChange,
  onContextWindowChange,
  onFastModeChange,
  canChangeAdapter = true,
}: AgentConfigControlsProps) {
  const themeColors = useThemeColors();
  const [modeSheetOpen, setModeSheetOpen] = useState(false);
  const [configSheetOpen, setConfigSheetOpen] = useState(false);
  const fastModeFlagEnabled = !!useFeatureFlag(FAST_MODE_FLAG);

  const executionModes = getMobileExecutionModes(
    getAvailableModesForAdapter(adapter),
  );
  const modelConfigOption = getModelConfigOption(configOptions);
  // A running session locks the adapter, so hide the other harness's models —
  // picking one on a live session would push an invalid model to the run.
  const mobileModelGroups = useMemo(() => {
    const filtered = canChangeAdapter
      ? modelGroups
      : modelGroups
          .map((group) => ({
            ...group,
            options: group.options.filter(
              (option) =>
                harnessForModel(modelGroups, option.value) === adapter,
            ),
          }))
          .filter((group) => group.options.length > 0);
    return toMobileModelGroups(filtered);
  }, [modelGroups, canChangeAdapter, adapter]);
  const reasoningOptions = getReasoningEffortOptions(adapter, model) ?? [];
  const presets = useMemo(
    () => getAgentPresets(adapter, modelConfigOption),
    [adapter, modelConfigOption],
  );

  const modelLabel = findModelOptionInGroups(modelGroups, model)?.name ?? model;
  const effortLabel =
    reasoningOptions.find((option) => option.value === reasoning)?.name ??
    reasoning;
  const configLabel =
    reasoningOptions.length > 0 ? `${modelLabel} · ${effortLabel}` : modelLabel;

  const fastModeAvailable =
    fastModeFlagEnabled && adapter === "claude" && supportsFastMode(model);
  const fastActive = fastModeAvailable && fastMode;
  const contextWindowAvailable = supports1MContext(model);

  const applyPreset = (preset: AgentPreset) => {
    if (preset.model !== model) onModelChange(preset.model);
    if (preset.effort !== reasoning) onReasoningChange(preset.effort);
  };

  const handleModelChange = (next: string) => {
    const pickedHarness = harnessForModel(modelGroups, next);
    if (pickedHarness !== adapter) {
      onAdapterChange(resolveCrossHarnessModelSelection(pickedHarness, next));
      return;
    }
    onModelChange(next);
  };

  const handleReset = () => {
    const middle = getMiddlePreset(presets);
    if (middle) applyPreset(middle);
    if (contextWindow !== DEFAULT_CONTEXT_WINDOW) {
      onContextWindowChange(DEFAULT_CONTEXT_WINDOW);
    }
    if (fastMode) onFastModeChange(false);
  };

  return (
    <>
      <Pill
        icon={modeIcon(
          mode,
          mode === "plan" ? themeColors.accent[11] : themeColors.gray[11],
        )}
        label={
          executionModes.find((option) => option.id === mode)?.name ?? mode
        }
        accent={mode === "plan"}
        onPress={() => setModeSheetOpen(true)}
      />

      <Pill
        icon={
          fastActive ? (
            <Lightning
              size={14}
              color={themeColors.status.warning}
              weight="fill"
            />
          ) : adapter === "codex" ? (
            <Cpu size={14} color={themeColors.gray[11]} />
          ) : (
            <Robot size={14} color={themeColors.gray[11]} />
          )
        }
        label={configLabel}
        onPress={() => setConfigSheetOpen(true)}
      />

      <SelectSheet
        open={modeSheetOpen}
        title="Execution mode"
        value={mode}
        onChange={(value) => onModeChange(value as ExecutionMode)}
        onClose={() => setModeSheetOpen(false)}
        options={executionModes.map((option) => ({
          value: option.id,
          label: option.name,
          description: option.description,
          icon: modeIcon(
            option.id as ExecutionMode,
            option.id === "plan"
              ? themeColors.accent[11]
              : themeColors.gray[11],
            16,
          ),
        }))}
      />

      <AgentConfigSheet
        open={configSheetOpen}
        onClose={() => setConfigSheetOpen(false)}
        model={model}
        reasoning={reasoning}
        contextWindow={contextWindow}
        fastMode={fastActive}
        presets={presets}
        reasoningOptions={reasoningOptions}
        modelGroups={mobileModelGroups}
        fastModeAvailable={fastModeAvailable}
        contextWindowAvailable={contextWindowAvailable}
        onSelectPreset={applyPreset}
        onModelChange={handleModelChange}
        onReasoningChange={onReasoningChange}
        onFastModeChange={onFastModeChange}
        onContextWindowChange={onContextWindowChange}
        onReset={handleReset}
      />
    </>
  );
}
