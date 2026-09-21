import type { Adapter } from "./adapter";
import { EFFORT_LEVEL_LABELS, type EffortLevel } from "./domain-types";
import { reasoningEffortsForModel } from "./model-catalog";
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
