import type { Adapter } from "@posthog/shared";
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

/** One stop on the Faster/Smarter slider: a model plus effort pairing. */
export interface CapabilityNotch {
  model: string;
  effort: EffortLevel;
}

const CLAUDE_CAPABILITY_LADDER: CapabilityNotch[] = [
  { model: "claude-sonnet-5", effort: "medium" },
  { model: "claude-sonnet-5", effort: "high" },
  { model: "claude-opus-5", effort: "medium" },
  { model: "claude-opus-5", effort: "xhigh" },
  { model: "claude-fable-5", effort: "max" },
];

const CODEX_CAPABILITY_LADDER: CapabilityNotch[] = [
  { model: "gpt-5.6-terra", effort: "low" },
  { model: "gpt-5.6-sol", effort: "low" },
  { model: "gpt-5.6-sol", effort: "medium" },
  { model: "gpt-5.6-sol", effort: "high" },
  { model: "gpt-5.6-sol", effort: "xhigh" },
];

export function getCapabilityLadder(adapter: Adapter): CapabilityNotch[] {
  return adapter === "codex"
    ? CODEX_CAPABILITY_LADDER
    : CLAUDE_CAPABILITY_LADDER;
}
