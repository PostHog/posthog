import { getAvailableModesForAdapter } from "@posthog/core/sessions/executionModes";
import type { CloudComposerSelection } from "@posthog/core/task-detail/composerModelPolicy";
import {
  type Adapter,
  type CloudTaskConfigOption,
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
import { type ReactNode, useState } from "react";
import { useThemeColors } from "@/lib/theme";
import { AgentConfigSheet } from "./AgentConfigSheet";
import {
  type AgentPreset,
  type ContextWindow,
  DEFAULT_CONTEXT_WINDOW,
  getAgentPresets,
  getComposerModelOptions,
  getConfigOptionLabel,
  getMiddlePreset,
  getMobileExecutionModes,
  getModelConfigOption,
  resolveHarnessSwitchSelection,
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
  const modelOptions = getComposerModelOptions(modelConfigOption);
  const reasoningOptions = getReasoningEffortOptions(adapter, model) ?? [];
  const presets = getAgentPresets(adapter, modelConfigOption);

  const modelLabel =
    getConfigOptionLabel(modelConfigOption.options, model) ?? model;
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
        adapter={adapter}
        model={model}
        reasoning={reasoning}
        contextWindow={contextWindow}
        fastMode={fastActive}
        presets={presets}
        reasoningOptions={reasoningOptions}
        modelOptions={modelOptions}
        fastModeAvailable={fastModeAvailable}
        contextWindowAvailable={contextWindowAvailable}
        canChangeAdapter={canChangeAdapter}
        onSelectPreset={applyPreset}
        onModelChange={onModelChange}
        onReasoningChange={onReasoningChange}
        onAdapterSelect={(next) => {
          if (next !== adapter) {
            onAdapterChange(resolveHarnessSwitchSelection(adapter));
          }
        }}
        onFastModeChange={onFastModeChange}
        onContextWindowChange={onContextWindowChange}
        onReset={handleReset}
      />
    </>
  );
}
