import type { Signal } from "@posthog/shared/types";

/**
 * Under this many signals, a flat list reads fine; grouping would be more
 * chrome than help.
 */
export const FLAT_SIGNALS_MAX = 4;

/** Signals shown per source group before the "Show all" expander. */
export const GROUP_PREVIEW_COUNT = 2;

export interface SignalSourceGroup {
  sourceProduct: string;
  signals: Signal[];
}

export function shouldGroupSignals(signals: Signal[]): boolean {
  return signals.length > FLAT_SIGNALS_MAX;
}

/**
 * Evidence grouped by source product, in first-seen order so the grouping
 * respects the API's relevance ordering. A report with 50 error-tracking
 * exceptions reads as one section with a count instead of a wall of cards.
 */
export function groupReportSignals(signals: Signal[]): SignalSourceGroup[] {
  const groups = new Map<string, Signal[]>();
  for (const signal of signals) {
    const existing = groups.get(signal.source_product);
    if (existing) {
      existing.push(signal);
    } else {
      groups.set(signal.source_product, [signal]);
    }
  }
  return [...groups.entries()].map(([sourceProduct, grouped]) => ({
    sourceProduct,
    signals: grouped,
  }));
}
