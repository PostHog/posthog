import type { ScoutScratchpadEntry } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  filterScratchpadEntries,
  groupScratchpadEntries,
  humanizeNamespace,
  scoutDisplayName,
  scratchpadNamespaceOf,
  splitScratchpadKey,
} from "./scoutScratchpad";

function entry(
  key: string,
  content: string,
  updatedAt: string,
): ScoutScratchpadEntry {
  return {
    key,
    content,
    created_at: updatedAt,
    updated_at: updatedAt,
    created_by_run_id: null,
  };
}

describe("scratchpadNamespaceOf", () => {
  it.each([
    ["tags:errors:taxonomy", "tags"],
    ["dedupe:abc", "dedupe"],
    ["no-namespace", "general"],
    [":leading-colon", "general"],
  ])("%s → %s", (key, expected) => {
    expect(scratchpadNamespaceOf(key)).toBe(expected);
  });
});

describe("humanizeNamespace", () => {
  it.each([
    ["general", "General"],
    ["tags", "Tags"],
    ["watch-list", "Watch List"],
    ["error_tracking", "Error Tracking"],
  ])("%s → %s", (namespace, expected) => {
    expect(humanizeNamespace(namespace)).toBe(expected);
  });
});

describe("splitScratchpadKey", () => {
  it("splits on the first colon", () => {
    expect(splitScratchpadKey("tags:errors:taxonomy")).toEqual({
      kind: "tags",
      body: "errors:taxonomy",
    });
  });

  it("returns a null kind for keys without a prefix", () => {
    expect(splitScratchpadKey("standalone")).toEqual({
      kind: null,
      body: "standalone",
    });
  });
});

describe("scoutDisplayName", () => {
  it("strips the fleet prefix", () => {
    expect(scoutDisplayName("signals-scout-apm")).toBe("apm");
  });

  it("leaves non-fleet names untouched", () => {
    expect(scoutDisplayName("custom-scout")).toBe("custom-scout");
  });
});

describe("groupScratchpadEntries", () => {
  it("clusters by namespace and orders clusters by most recent entry", () => {
    const entries = [
      entry("watch:b", "newest overall", "2026-06-03T00:00:00Z"),
      entry("tags:a", "older", "2026-06-01T00:00:00Z"),
      entry("watch:a", "middle", "2026-06-02T00:00:00Z"),
    ];

    const groups = groupScratchpadEntries(entries);

    // `watch` floats above `tags` because its newest entry is more recent.
    expect(groups.map((group) => group.namespace)).toEqual(["watch", "tags"]);
    // Input order is preserved within a cluster.
    expect(groups[0]?.entries.map((e) => e.key)).toEqual([
      "watch:b",
      "watch:a",
    ]);
    expect(groups[0]?.label).toBe("Watch");
  });

  it("returns an empty list for no entries", () => {
    expect(groupScratchpadEntries([])).toEqual([]);
  });
});

describe("filterScratchpadEntries", () => {
  const entries = [
    entry("tags:errors", "taxonomy for error tracking", "2026-06-01T00:00:00Z"),
    entry("dedupe:replay", "fingerprint logic", "2026-06-02T00:00:00Z"),
  ];

  it("returns all entries for an empty query", () => {
    expect(filterScratchpadEntries(entries, "  ")).toHaveLength(2);
  });

  it("matches on key", () => {
    expect(filterScratchpadEntries(entries, "DEDUPE")).toEqual([entries[1]]);
  });

  it("matches on content", () => {
    expect(filterScratchpadEntries(entries, "taxonomy")).toEqual([entries[0]]);
  });

  it("returns nothing when no entry matches", () => {
    expect(filterScratchpadEntries(entries, "nomatch")).toEqual([]);
  });
});
