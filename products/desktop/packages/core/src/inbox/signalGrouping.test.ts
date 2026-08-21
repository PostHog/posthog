import type { Signal } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";

import { groupReportSignals, shouldGroupSignals } from "./signalGrouping";

function signal(id: string, sourceProduct: string): Signal {
  return {
    signal_id: id,
    content: "c",
    source_product: sourceProduct,
    source_type: "t",
    source_id: id,
    weight: 1,
    timestamp: "2026-08-20T00:00:00Z",
    extra: {},
  };
}

describe("signalGrouping", () => {
  it("keeps small evidence sets flat", () => {
    const signals = [signal("a", "error_tracking"), signal("b", "replay")];
    expect(shouldGroupSignals(signals)).toBe(false);
  });

  it("groups by source in first-seen order, preserving in-group order", () => {
    const signals = [
      signal("e1", "error_tracking"),
      signal("r1", "replay"),
      signal("e2", "error_tracking"),
      signal("c1", "conversations"),
      signal("e3", "error_tracking"),
    ];
    expect(shouldGroupSignals(signals)).toBe(true);
    const groups = groupReportSignals(signals);
    expect(groups.map((g) => g.sourceProduct)).toEqual([
      "error_tracking",
      "replay",
      "conversations",
    ]);
    expect(groups[0].signals.map((s) => s.signal_id)).toEqual([
      "e1",
      "e2",
      "e3",
    ]);
  });
});
