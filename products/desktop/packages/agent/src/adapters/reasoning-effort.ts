import {
  type Adapter,
  type CapabilityNotch,
  getCapabilityLadder,
} from "@posthog/shared";
import type { EffortLevel } from "@posthog/shared/domain-types";
import {
  getContextWindowOptions as getClaudeContextWindowOptions,
  getEffortOptions as getClaudeEffortOptions,
  getFastModeOptions as getClaudeFastModeOptions,
} from "./claude/session/models";
import { getReasoningEffortOptions as getCodexReasoningEffortOptions } from "./codex-app-server/models";

export type SupportedReasoningEffort = EffortLevel;

export interface ReasoningEffortOption {
  value: SupportedReasoningEffort;
  name: string;
  _meta?: Record<string, unknown>;
}

export function getReasoningEffortOptions(
  adapter: Adapter,
  modelId: string,
): ReasoningEffortOption[] | null {
  const options =
    adapter === "codex"
      ? getCodexReasoningEffortOptions(modelId)
      : getClaudeEffortOptions(modelId);

  return options as ReasoningEffortOption[] | null;
}

export function isSupportedReasoningEffort(
  adapter: Adapter,
  modelId: string,
  value: string,
): value is SupportedReasoningEffort {
  return (
    getReasoningEffortOptions(adapter, modelId)?.some(
      (option) => option.value === value,
    ) ?? false
  );
}

export interface SessionToggleOption {
  value: string;
  name: string;
  _meta?: Record<string, unknown>;
}

export function getContextWindowOptions(
  adapter: Adapter,
  modelId: string,
): SessionToggleOption[] | null {
  return adapter === "codex" ? null : getClaudeContextWindowOptions(modelId);
}

export function getFastModeOptions(
  adapter: Adapter,
  modelId: string,
): SessionToggleOption[] | null {
  return adapter === "codex" ? null : getClaudeFastModeOptions(modelId);
}

export { type CapabilityNotch, getCapabilityLadder };
