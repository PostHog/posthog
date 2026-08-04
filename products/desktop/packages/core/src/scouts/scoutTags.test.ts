import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  configMatchesScoutTags,
  listScoutTagOptions,
  MAX_SCOUT_TAG_LENGTH,
  MAX_SCOUT_TAGS,
  normalizeScoutTag,
  parseScoutTagsInput,
  scoutTags,
  withScoutTagRemoved,
  withScoutTagsAdded,
} from "./scoutTags";

function makeConfig(overrides: Partial<ScoutConfig> = {}): ScoutConfig {
  return {
    id: "config-1",
    skill_name: "signals-scout-error-tracking",
    enabled: true,
    emit: true,
    run_interval_minutes: 60,
    last_run_at: "2026-06-10T11:00:00Z",
    created_at: "2026-06-01T00:00:00Z",
    ...overrides,
  };
}

describe("normalizeScoutTag", () => {
  it.each([
    ["Revenue", "revenue"],
    ["on call", "on-call"],
    ["  spaced  out  ", "spaced-out"],
    ["cost_spike", "cost-spike"],
    ["billing/usage", "billingusage"],
    ["--dashes--", "dashes"],
    ["a---b", "a-b"],
    ["!!!", ""],
    ["", ""],
  ])("normalizes %j to %j", (raw, expected) => {
    expect(normalizeScoutTag(raw)).toBe(expected);
  });
});

describe("parseScoutTagsInput", () => {
  it("splits on commas and drops entries that normalize to nothing", () => {
    expect(parseScoutTagsInput("Revenue, on call, !!!, ")).toEqual({
      tags: ["revenue", "on-call"],
      tooLong: [],
    });
  });

  it("dedupes entries that normalize to the same tag", () => {
    expect(parseScoutTagsInput("revenue, Revenue").tags).toEqual(["revenue"]);
  });

  it("reports an over-long tag rather than swallowing it", () => {
    const long = "a".repeat(MAX_SCOUT_TAG_LENGTH + 1);
    expect(parseScoutTagsInput(`revenue, ${long}`)).toEqual({
      tags: ["revenue"],
      tooLong: [long],
    });
  });
});

describe("withScoutTagsAdded", () => {
  it("returns the full sorted replacement set", () => {
    expect(withScoutTagsAdded(["revenue"], ["on-call"])).toEqual([
      "on-call",
      "revenue",
    ]);
  });

  it("returns null when nothing would change, so no request is sent", () => {
    expect(withScoutTagsAdded(["revenue"], ["revenue"])).toBeNull();
    expect(withScoutTagsAdded(["revenue"], [])).toBeNull();
  });

  it("stops at the cap instead of sending a set the server would reject", () => {
    const existing = Array.from({ length: MAX_SCOUT_TAGS }, (_, i) => `t${i}`);
    expect(withScoutTagsAdded(existing, ["extra"])).toBeNull();
  });
});

describe("withScoutTagRemoved", () => {
  it("returns the remaining tags", () => {
    expect(withScoutTagRemoved(["on-call", "revenue"], "on-call")).toEqual([
      "revenue",
    ]);
  });

  it("returns null for a tag the scout does not carry", () => {
    expect(withScoutTagRemoved(["revenue"], "on-call")).toBeNull();
  });
});

describe("scoutTags", () => {
  it("treats a backend predating the field as untagged", () => {
    expect(scoutTags(makeConfig({ tags: undefined }))).toEqual([]);
  });
});

describe("listScoutTagOptions", () => {
  it("orders by usage then alphabetically", () => {
    const options = listScoutTagOptions([
      makeConfig({ id: "a", tags: ["revenue", "on-call"] }),
      makeConfig({ id: "b", tags: ["revenue"] }),
      makeConfig({ id: "c", tags: ["alerts"] }),
      makeConfig({ id: "d", tags: [] }),
    ]);
    expect(options).toEqual([
      { tag: "revenue", count: 2 },
      { tag: "alerts", count: 1 },
      { tag: "on-call", count: 1 },
    ]);
  });
});

describe("configMatchesScoutTags", () => {
  const config = makeConfig({ tags: ["revenue"] });

  it("matches everything when nothing is selected", () => {
    expect(configMatchesScoutTags(config, [])).toBe(true);
  });

  it("is any-of, matching the server's overlap filter", () => {
    expect(configMatchesScoutTags(config, ["revenue", "on-call"])).toBe(true);
    expect(configMatchesScoutTags(config, ["on-call"])).toBe(false);
  });
});
