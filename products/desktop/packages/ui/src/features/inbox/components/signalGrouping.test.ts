import type { Signal } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import { groupSignalsByType, shouldGroupSignals } from "./signalGrouping";

function makeSignal(
  overrides: Partial<Signal> & { signal_id: string },
): Signal {
  return {
    content: "",
    source_product: "github",
    source_type: "issue",
    source_id: "src-1",
    weight: 1,
    timestamp: "2026-08-01T00:00:00Z",
    extra: {},
    ...overrides,
  };
}

describe("signalGrouping", () => {
  it("buckets by source line and keeps incoming order within each group", () => {
    const signals = [
      makeSignal({ signal_id: "gh-1" }),
      makeSignal({
        signal_id: "err-1",
        source_product: "error_tracking",
        source_type: "issue_created",
      }),
      makeSignal({ signal_id: "gh-2" }),
      makeSignal({
        signal_id: "err-2",
        source_product: "error_tracking",
        source_type: "issue_created",
      }),
      makeSignal({ signal_id: "gh-3" }),
    ];

    const groups = groupSignalsByType(signals);

    expect(groups.map((g) => g.label)).toEqual([
      "GitHub · Issue",
      "Error tracking · New issue",
    ]);
    expect(groups[0].signals.map((s) => s.signal_id)).toEqual([
      "gh-1",
      "gh-2",
      "gh-3",
    ]);
    expect(groups[1].signals.map((s) => s.signal_id)).toEqual([
      "err-1",
      "err-2",
    ]);
  });

  it("splits scout findings by skill instead of one scout bucket", () => {
    const scout = (signal_id: string, skill_name: string): Signal =>
      makeSignal({
        signal_id,
        source_product: "signals_scout",
        source_type: "cross_source_issue",
        extra: { skill_name },
      });
    const groups = groupSignalsByType([
      scout("s-1", "signals-scout-error-tracking"),
      scout("s-2", "signals-scout-session-replay"),
      scout("s-3", "signals-scout-error-tracking"),
    ]);

    expect(groups.map((g) => [g.label, g.signals.length])).toEqual([
      ["Scout · Error tracking", 2],
      ["Scout · Session replay", 1],
    ]);
  });

  it("orders groups largest first, first-appearance on ties", () => {
    const groups = groupSignalsByType([
      makeSignal({
        signal_id: "z-1",
        source_product: "zendesk",
        source_type: "ticket",
      }),
      makeSignal({ signal_id: "gh-1" }),
      makeSignal({
        signal_id: "err-1",
        source_product: "error_tracking",
        source_type: "issue_spiking",
      }),
      makeSignal({
        signal_id: "err-2",
        source_product: "error_tracking",
        source_type: "issue_spiking",
      }),
      makeSignal({ signal_id: "gh-2" }),
    ]);

    expect(groups.map((g) => g.label)).toEqual([
      "GitHub · Issue",
      "Error tracking · Volume spike",
      "Zendesk · Ticket",
    ]);
    expect(groups.map((g) => g.signals.length)).toEqual([2, 2, 1]);
  });

  it.each([
    { name: "below minimum count", total: 4, distinct: 2, expected: false },
    { name: "no type repeats", total: 5, distinct: 5, expected: false },
    {
      name: "enough findings with repeats",
      total: 5,
      distinct: 2,
      expected: true,
    },
    { name: "single repeated type", total: 6, distinct: 1, expected: true },
  ])(
    "grouping engages only when it compresses: $name",
    ({ total, distinct, expected }) => {
      const signals = Array.from({ length: total }, (_, i) =>
        makeSignal({
          signal_id: `s-${i}`,
          source_type: `type_${i % distinct}`,
        }),
      );
      const groups = groupSignalsByType(signals);
      expect(groups).toHaveLength(distinct);
      expect(shouldGroupSignals(groups, signals.length)).toBe(expected);
    },
  );
});
