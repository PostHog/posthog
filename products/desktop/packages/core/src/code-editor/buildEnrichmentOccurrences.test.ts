import type { SerializedEnrichment } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { buildEnrichmentOccurrences } from "./buildEnrichmentOccurrences";

function emptyEnrichment(): SerializedEnrichment {
  return { flags: [], events: [] };
}

describe("buildEnrichmentOccurrences", () => {
  it("returns empty array for null", () => {
    expect(buildEnrichmentOccurrences(null)).toEqual([]);
  });

  it("offsets line numbers by 1 and tags entries", () => {
    const data: SerializedEnrichment = {
      ...emptyEnrichment(),
      flags: [
        {
          flagKey: "my-flag",
          flagId: null,
          flagType: "boolean",
          staleness: null,
          rollout: null,
          active: true,
          variants: [],
          experiment: null,
          occurrences: [
            { method: "isFeatureEnabled", line: 4, startCol: 2, endCol: 8 },
          ],
        },
      ],
    };
    const out = buildEnrichmentOccurrences(data);
    expect(out).toHaveLength(1);
    expect(out[0].line).toBe(5);
    expect(out[0].entry.kind).toBe("flag");
    expect(out[0].summary).toBe("Flag: my-flag");
  });

  it("sorts occurrences into document order", () => {
    const data: SerializedEnrichment = {
      ...emptyEnrichment(),
      flags: [
        {
          flagKey: "f",
          flagId: null,
          flagType: "boolean",
          staleness: null,
          rollout: null,
          active: true,
          variants: [],
          experiment: null,
          occurrences: [
            { method: "isFeatureEnabled", line: 9, startCol: 0, endCol: 1 },
            { method: "isFeatureEnabled", line: 1, startCol: 5, endCol: 6 },
            { method: "isFeatureEnabled", line: 1, startCol: 1, endCol: 2 },
          ],
        },
      ],
    };
    const out = buildEnrichmentOccurrences(data);
    expect(out.map((o) => [o.line, o.startCol])).toEqual([
      [2, 1],
      [2, 5],
      [10, 0],
    ]);
  });
});
