import type { PrDiffStats } from "@posthog/core/git/router-schemas";
import { createContext, useContext } from "react";

export interface PrDiffStatsBatchContextValue {
  batch: Record<string, PrDiffStats> | undefined;
  isLoading: boolean;
  /** True only when a provider is mounted, so consumers know to skip the per-PR fallback. */
  hasBatch: boolean;
}

const DEFAULT_VALUE: PrDiffStatsBatchContextValue = {
  batch: undefined,
  isLoading: false,
  hasBatch: false,
};

export const PrDiffStatsBatchContext =
  createContext<PrDiffStatsBatchContextValue>(DEFAULT_VALUE);

/**
 * Read a specific PR's diff stats from the surrounding batch context.
 * `hasBatch` is false when no provider wraps the consumer; the per-PR
 * `PrDiffStats` falls back to its own query in that case (detail view).
 */
export function usePrDiffStatsFromBatch(prUrl: string | null | undefined): {
  stats: PrDiffStats | undefined;
  isLoading: boolean;
  hasBatch: boolean;
} {
  const ctx = useContext(PrDiffStatsBatchContext);
  return {
    stats: prUrl && ctx.batch ? ctx.batch[prUrl] : undefined,
    isLoading: ctx.isLoading,
    hasBatch: ctx.hasBatch,
  };
}
