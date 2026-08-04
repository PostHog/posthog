import type {
  SessionConfigOption,
  SessionConfigSelectGroup,
} from "@agentclientprotocol/sdk";
import type {
  PiModelSelection,
  PiThinkingLevel,
} from "@posthog/core/pi-runtime/piSessionController";
import type { AgentHarness } from "@posthog/ui/features/sessions/components/HarnessSubmenu";
import { ReasoningLevelSelector } from "@posthog/ui/features/sessions/components/ReasoningLevelSelector";
import { useMemo } from "react";

const THINKING_LEVEL_LABELS: Record<PiThinkingLevel, string> = {
  off: "Off",
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra High",
  max: "Max",
};

function modelKey(model: PiModelSelection): string {
  return JSON.stringify([model.provider, model.id]);
}

type PiModelOption = PiModelSelection & { name?: string };

interface PiReasoningLevelSelectorProps {
  models: PiModelOption[];
  currentModel?: PiModelOption;
  thinkingLevels: PiThinkingLevel[];
  currentThinkingLevel?: PiThinkingLevel;
  disabled?: boolean;
  isLoading?: boolean;
  onModelChange: (model: PiModelSelection) => void;
  onThinkingLevelChange: (level: PiThinkingLevel) => void;
  onHarnessChange?: (harness: AgentHarness) => void;
}

/**
 * Pi's merged model + thinking control: adapts the Pi model catalog and
 * thinking levels into session config options so Pi surfaces render the same
 * unified pill as ACP sessions (ReasoningLevelSelector).
 */
export function PiReasoningLevelSelector({
  models,
  currentModel,
  thinkingLevels,
  currentThinkingLevel,
  disabled,
  isLoading,
  onModelChange,
  onThinkingLevelChange,
  onHarnessChange,
}: PiReasoningLevelSelectorProps) {
  // A session can be on a model the catalog no longer lists; keep it pickable
  // so the pill labels it instead of falling back to its raw key.
  const listedModels = useMemo(() => {
    if (!currentModel) return models;
    const currentKey = modelKey(currentModel);
    const isListed = models.some((model) => modelKey(model) === currentKey);
    return isListed ? models : [...models, currentModel];
  }, [models, currentModel]);

  const modelOption = useMemo<SessionConfigOption | undefined>(() => {
    if (listedModels.length === 0) return undefined;
    const groups = new Map<string, SessionConfigSelectGroup>();
    for (const model of listedModels) {
      const group = groups.get(model.provider) ?? {
        group: model.provider,
        name: model.provider,
        options: [],
      };
      group.options.push({
        value: modelKey(model),
        name: model.name ?? model.id,
      });
      groups.set(model.provider, group);
    }
    return {
      type: "select",
      id: "model",
      name: "Model",
      category: "model",
      currentValue: currentModel ? modelKey(currentModel) : "",
      options: [...groups.values()],
    };
  }, [listedModels, currentModel]);

  const supportsThinking = thinkingLevels.some((level) => level !== "off");
  const thoughtOption = useMemo<SessionConfigOption | undefined>(() => {
    if (!supportsThinking || !currentThinkingLevel) return undefined;
    return {
      type: "select",
      id: "thinking",
      name: "Thinking",
      category: "thought_level",
      currentValue: currentThinkingLevel,
      options: thinkingLevels.map((level) => ({
        value: level,
        name: THINKING_LEVEL_LABELS[level] ?? level,
      })),
    };
  }, [supportsThinking, currentThinkingLevel, thinkingLevels]);

  return (
    <ReasoningLevelSelector
      thoughtOption={thoughtOption}
      modelOption={modelOption}
      onChange={(value) => {
        if (thinkingLevels.includes(value as PiThinkingLevel)) {
          onThinkingLevelChange(value as PiThinkingLevel);
        }
      }}
      onModelChange={(value) => {
        const model = listedModels.find(
          (candidate) => modelKey(candidate) === value,
        );
        if (model) onModelChange(model);
      }}
      harness="pi"
      includePiHarness
      onHarnessChange={onHarnessChange}
      disabled={disabled}
      isLoading={isLoading}
    />
  );
}
