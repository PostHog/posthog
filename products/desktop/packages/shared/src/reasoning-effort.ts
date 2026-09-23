import type { Adapter } from "./adapter";
import { EFFORT_LEVEL_LABELS, type EffortLevel } from "./domain-types";
import { normalizeModelId, reasoningEffortsForModel } from "./model-catalog";
import {
  CAPABILITY_LADDER_BY_RUNTIME_ADAPTER,
  type CapabilityNotch,
} from "./model-catalog.generated";

export type SupportedReasoningEffort = EffortLevel;

export const DEFAULT_REASONING_EFFORT: SupportedReasoningEffort = "high";

export interface ReasoningEffortOption {
  value: SupportedReasoningEffort;
  name: string;
}

/** Null rather than an empty list for a model with no effort control, so the
 * caller renders no dropdown instead of an empty one. */
export function getReasoningEffortOptions(
  adapter: Adapter,
  modelId: string,
): ReasoningEffortOption[] | null {
  const efforts = reasoningEffortsForModel(adapter, modelId);
  if (efforts.length === 0) return null;
  return efforts.map((value) => ({ value, name: EFFORT_LEVEL_LABELS[value] }));
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

export type { CapabilityNotch };

export function getCapabilityLadder(
  adapter: Adapter,
): readonly CapabilityNotch[] {
  return CAPABILITY_LADDER_BY_RUNTIME_ADAPTER[adapter];
}

const MODELS_WITH_1M_CONTEXT = new Set([
  "claude-opus-4-7",
  "claude-opus-4-8",
  "claude-opus-5",
  "claude-opus-5-5",
  "claude-sonnet-4-6",
  "claude-sonnet-5",
  "claude-fable-5",
  "claude-fable-5-1",
]);

// Normalized like the effort lookup above: the gateway serves some ids provider-qualified,
// and a raw check here would silently drop the model to 200k.
export function supports1MContext(modelId: string): boolean {
  return MODELS_WITH_1M_CONTEXT.has(normalizeModelId(modelId));
}

const MODELS_WITH_FAST_MODE = new Set([
  "claude-opus-4-7",
  "claude-opus-4-8",
  "claude-opus-5",
  "claude-opus-5-5",
]);

export function supportsFastMode(modelId: string): boolean {
  return MODELS_WITH_FAST_MODE.has(normalizeModelId(modelId));
}
