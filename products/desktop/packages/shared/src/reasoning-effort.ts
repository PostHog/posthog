import type { Adapter } from "./adapter";
import { EFFORT_LEVEL_LABELS, type EffortLevel } from "./domain-types";

export type SupportedReasoningEffort = EffortLevel;

export const DEFAULT_REASONING_EFFORT: SupportedReasoningEffort = "high";

export interface ReasoningEffortOption {
  value: SupportedReasoningEffort;
  name: string;
}

const BASE_OPTIONS: ReasoningEffortOption[] = [
  { value: "low", name: "Low" },
  { value: "medium", name: "Medium" },
  { value: "high", name: "High" },
];

const STANDARD_EFFORTS: readonly SupportedReasoningEffort[] = [
  "low",
  "medium",
  "high",
];
const EXTENDED_EFFORTS: readonly SupportedReasoningEffort[] = [
  ...STANDARD_EFFORTS,
  "xhigh",
  "max",
  "ultracode",
];

const CLAUDE_MODEL_EFFORTS: Readonly<
  Record<string, readonly SupportedReasoningEffort[]>
> = {
  "claude-opus-4-7": EXTENDED_EFFORTS,
  "claude-opus-4-8": EXTENDED_EFFORTS,
  "claude-sonnet-4-6": STANDARD_EFFORTS,
  "claude-sonnet-5": EXTENDED_EFFORTS,
  "claude-fable-5": EXTENDED_EFFORTS,
  "@cf/zai-org/glm-5.2": ["high", "max"],
  "zai-org/glm-5.3": ["high", "max"],
  "claude-opus-5": EXTENDED_EFFORTS,
};

export function getReasoningEffortOptions(
  adapter: Adapter,
  modelId: string,
): ReasoningEffortOption[] | null {
  if (adapter === "claude") {
    const efforts = CLAUDE_MODEL_EFFORTS[modelId];
    return (
      efforts?.map((value) => ({ value, name: EFFORT_LEVEL_LABELS[value] })) ??
      null
    );
  }

  const options = [...BASE_OPTIONS];
  const normalizedModelId = modelId.toLowerCase();
  const supportsXhigh =
    normalizedModelId.includes("gpt-5.5") ||
    normalizedModelId.includes("gpt-5.6");

  if (supportsXhigh) {
    options.push({ value: "xhigh", name: "Extra High" });
  }
  if (adapter === "codex" && normalizedModelId.includes("gpt-5.6")) {
    options.push({ value: "max", name: "Max" });
  }

  return options;
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

/** One stop on the Faster/Smarter capability scale: a model plus effort pairing. */
export interface CapabilityNotch {
  model: string;
  effort: SupportedReasoningEffort;
}

// Mirrors the desktop ladder in @posthog/agent (unreachable from mobile); the
// two must stay in sync.
const CLAUDE_CAPABILITY_LADDER: readonly CapabilityNotch[] = [
  { model: "claude-sonnet-5", effort: "medium" },
  { model: "claude-sonnet-5", effort: "high" },
  { model: "claude-opus-5", effort: "medium" },
  { model: "claude-opus-5", effort: "xhigh" },
  { model: "claude-fable-5", effort: "max" },
];

const CODEX_CAPABILITY_LADDER: readonly CapabilityNotch[] = [
  { model: "gpt-5.6-terra", effort: "low" },
  { model: "gpt-5.6-sol", effort: "low" },
  { model: "gpt-5.6-sol", effort: "medium" },
  { model: "gpt-5.6-sol", effort: "high" },
  { model: "gpt-5.6-sol", effort: "xhigh" },
];

export function getCapabilityLadder(
  adapter: Adapter,
): readonly CapabilityNotch[] {
  return adapter === "codex"
    ? CODEX_CAPABILITY_LADDER
    : CLAUDE_CAPABILITY_LADDER;
}

const MODELS_WITH_1M_CONTEXT = new Set([
  "claude-opus-4-7",
  "claude-opus-4-8",
  "claude-opus-5",
  "claude-sonnet-4-6",
  "claude-sonnet-5",
  "claude-fable-5",
]);

export function supports1MContext(modelId: string): boolean {
  return MODELS_WITH_1M_CONTEXT.has(modelId);
}

const MODELS_WITH_FAST_MODE = new Set([
  "claude-opus-4-7",
  "claude-opus-4-8",
  "claude-opus-5",
]);

export function supportsFastMode(modelId: string): boolean {
  return MODELS_WITH_FAST_MODE.has(modelId);
}
