import type { Signal } from "@posthog/shared/types";

/**
 * Under this many signals, a flat list reads fine; grouping would be more
 * chrome than help.
 */
export const FLAT_SIGNALS_MAX = 4;

/** Signals shown per source group before the "Show all" expander. */
export const GROUP_PREVIEW_COUNT = 2;

export interface SignalSourceGroup {
  /** Stable per-group identity: source product + source type. */
  key: string;
  sourceProduct: string;
  sourceType: string;
  signals: Signal[];
}

export function shouldGroupSignals(signals: Signal[]): boolean {
  return signals.length > FLAT_SIGNALS_MAX;
}

/**
 * Evidence grouped by source line (product + type), in first-seen order so
 * the grouping respects the API's relevance ordering. A report with 50
 * error-tracking exceptions reads as one section with a count instead of a
 * wall of cards, and mixed types from one product ("New issue" vs
 * "Regression") count separately.
 */
export function groupReportSignals(signals: Signal[]): SignalSourceGroup[] {
  const groups = new Map<string, SignalSourceGroup>();
  for (const signal of signals) {
    const key = `${signal.source_product}\u0000${signal.source_type}`;
    const existing = groups.get(key);
    if (existing) {
      existing.signals.push(signal);
    } else {
      groups.set(key, {
        key,
        sourceProduct: signal.source_product,
        sourceType: signal.source_type,
        signals: [signal],
      });
    }
  }
  return [...groups.values()];
}
