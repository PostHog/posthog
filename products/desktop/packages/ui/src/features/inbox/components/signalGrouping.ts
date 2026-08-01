import type { Signal } from "@posthog/shared/types";
import {
  parseExtra,
  signalCardSourceLine,
} from "@posthog/ui/features/inbox/components/detail/signalCardSourceLine";

export interface SignalGroup {
  /** Grouping key: the rendered source line, so it can never disagree with the header label. */
  key: string;
  label: string;
  sourceProduct: string;
  signals: Signal[];
}

/** Minimum findings before the grouped view engages. */
export const GROUPING_MIN_SIGNALS = 5;

/**
 * Bucket signals by their source line ("Product · Type"). Keying on the
 * rendered label rather than raw source_product/source_type splits scout
 * findings by skill instead of lumping every scout under one header. Groups
 * are ordered largest first (ties keep first-appearance order); the incoming
 * signal order is preserved within each group.
 */
export function groupSignalsByType(signals: Signal[]): SignalGroup[] {
  const groups = new Map<string, SignalGroup>();
  for (const signal of signals) {
    const label = signalCardSourceLine({
      ...signal,
      extra: parseExtra(signal.extra),
    });
    const group = groups.get(label);
    if (group) {
      group.signals.push(signal);
    } else {
      groups.set(label, {
        key: label,
        label,
        sourceProduct: signal.source_product,
        signals: [signal],
      });
    }
  }
  return [...groups.values()].sort(
    (a, b) => b.signals.length - a.signals.length,
  );
}

/**
 * The grouped view only helps when it actually compresses the list: enough
 * findings to be worth scanning by type, and at least one type that repeats.
 * Otherwise headers are pure overhead over the flat list.
 */
export function shouldGroupSignals(
  groups: SignalGroup[],
  signalCount: number,
): boolean {
  return signalCount >= GROUPING_MIN_SIGNALS && groups.length < signalCount;
}
