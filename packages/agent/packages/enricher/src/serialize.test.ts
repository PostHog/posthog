import { describe, expect, test } from "vitest";
import { EnrichedResult } from "./enriched-result.js";
import { ParseResult } from "./parse-result.js";
import { toSerializable } from "./serialize.js";
import type {
  EventDefinition,
  Experiment,
  FeatureFlag,
  PostHogCall,
} from "./types.js";

const call = (
  method: string,
  key: string,
  line: number,
  dynamic = false,
): PostHogCall => ({
  method,
  key,
  line,
  keyStartCol: 0,
  keyEndCol: 0,
  dynamic,
});

function makeParse(calls: PostHogCall[]): ParseResult {
  return new ParseResult("", "javascript", calls, [], [], [], []);
}

describe("toSerializable", () => {
  test("serialises flags with experiment + variants and drops runtime objects", () => {
    const flag: FeatureFlag = {
      id: 42,
      key: "new-onboarding",
      name: "New onboarding",
      active: true,
      filters: {
        multivariate: {
          variants: [
            { key: "control", rollout_percentage: 50 },
            { key: "test", rollout_percentage: 50 },
          ],
        },
        groups: [{ rollout_percentage: 100 }],
      } as unknown as Record<string, unknown>,
      created_at: "2026-01-01T00:00:00Z",
      created_by: null,
      deleted: false,
    };
    const experiment: Experiment = {
      id: 7,
      name: "Onboarding test",
      description: null,
      start_date: "2026-01-01",
      end_date: null,
      feature_flag_key: "new-onboarding",
      created_at: "2026-01-01T00:00:00Z",
      created_by: null,
    };

    const parsed = makeParse([call("isFeatureEnabled", "new-onboarding", 10)]);
    const enriched = new EnrichedResult(parsed, {
      flags: new Map([["new-onboarding", flag]]),
      experiments: [experiment],
    });

    const out = toSerializable(enriched);
    expect(out.events).toEqual([]);
    expect(out.flags).toHaveLength(1);

    const serialized = out.flags[0];
    expect(serialized.flagKey).toBe("new-onboarding");
    expect(serialized.flagId).toBe(42);
    expect(serialized.active).toBe(true);
    expect(serialized.flagType).toBe("multivariate");
    expect(serialized.variants).toEqual([
      { key: "control", rolloutPercentage: 50 },
      { key: "test", rolloutPercentage: 50 },
    ]);
    expect(serialized.occurrences).toEqual([
      { method: "isFeatureEnabled", line: 10, startCol: 0, endCol: 0 },
    ]);
    expect(serialized.experiment).toEqual({
      id: 7,
      name: "Onboarding test",
      status: "running",
    });

    // Must be JSON-safe (no class instances, Maps, etc.)
    expect(() => JSON.stringify(out)).not.toThrow();
    expect(JSON.parse(JSON.stringify(out))).toEqual(out);
  });

  test("marks experiment as complete when end_date is set", () => {
    const flag: FeatureFlag = {
      id: 1,
      key: "f",
      name: "F",
      active: true,
      filters: {},
      created_at: "2026-01-01T00:00:00Z",
      created_by: null,
      deleted: false,
    };
    const experiment: Experiment = {
      id: 3,
      name: "Done",
      description: null,
      start_date: "2026-01-01",
      end_date: "2026-02-01",
      feature_flag_key: "f",
      created_at: "2026-01-01T00:00:00Z",
      created_by: null,
    };

    const parsed = makeParse([call("isFeatureEnabled", "f", 5)]);
    const enriched = new EnrichedResult(parsed, {
      flags: new Map([["f", flag]]),
      experiments: [experiment],
    });

    const out = toSerializable(enriched);
    expect(out.flags[0].experiment?.status).toBe("complete");
  });

  test("serialises events with stats and description, skips dynamic occurrences", () => {
    const def: EventDefinition = {
      id: "def-abc",
      name: "signup_completed",
      description: "Fires when a user finishes signup",
      tags: ["onboarding"],
      last_seen_at: "2026-04-20T10:00:00Z",
      verified: true,
    };
    const parsed = makeParse([
      call("capture", "signup_completed", 12),
      call("capture", "signup_completed", 20),
      call("capture", "dynamic_event", 30, true),
    ]);
    const enriched = new EnrichedResult(parsed, {
      eventDefinitions: new Map([["signup_completed", def]]),
      eventStats: new Map([
        [
          "signup_completed",
          {
            volume: 1234,
            uniqueUsers: 456,
            lastSeenAt: "2026-04-22T10:00:00Z",
          },
        ],
      ]),
    });

    const out = toSerializable(enriched);
    expect(out.events).toHaveLength(1);
    const event = out.events[0];
    expect(event.eventName).toBe("signup_completed");
    expect(event.definitionId).toBe("def-abc");
    expect(event.verified).toBe(true);
    expect(event.description).toBe("Fires when a user finishes signup");
    expect(event.tags).toEqual(["onboarding"]);
    expect(event.volume).toBe(1234);
    expect(event.uniqueUsers).toBe(456);
    expect(event.lastSeenAt).toBe("2026-04-22T10:00:00Z");
    expect(event.occurrences).toEqual([
      { line: 12, dynamic: false, startCol: 0, endCol: 0 },
      { line: 20, dynamic: false, startCol: 0, endCol: 0 },
    ]);
  });

  test("returns empty arrays when nothing enriched", () => {
    const parsed = makeParse([]);
    const enriched = new EnrichedResult(parsed, {});
    expect(toSerializable(enriched)).toEqual({ flags: [], events: [] });
  });
});
