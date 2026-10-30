import { describe, expect, it } from "vitest";
import { upstreamTurnRetryDelayMs } from "./upstream-turn-retry";

describe("upstreamTurnRetryDelayMs", () => {
  it.each([
    [0, 15_000],
    [1, 30_000],
    [2, 60_000],
    [3, 120_000],
  ])("uses full jitter for retry %i with ceiling %i", (retries, ceiling) => {
    for (const random of [0, 0.5, 0.999999]) {
      const delay = upstreamTurnRetryDelayMs(
        "upstream_rate_limited",
        retries,
        0,
        () => random,
      );
      expect(delay).toBe(Math.floor(random * ceiling));
      expect(delay).toBeGreaterThanOrEqual(0);
      expect(delay).toBeLessThan(ceiling);
    }
  });

  it.each([
    [0, 12_300, 0, 12_300],
    [0, 1_000, 0.5, 8_500],
    [3, 150_000, 0.999999, 119_999],
    [0, 2_147_483_000, 0, 60_000],
  ])(
    "bounds the retry hint floor for retry %i",
    (retries, hint, random, expected) => {
      expect(
        upstreamTurnRetryDelayMs(
          "upstream_rate_limited",
          retries,
          hint,
          () => random,
        ),
      ).toBe(expected);
    },
  );

  it.each([0, 1, 2, 3])(
    "preserves jitter above a capped retry hint for retry %i",
    (retries) => {
      const delays = [0, 0.25, 0.5, 0.75, 0.999999].map((random) =>
        upstreamTurnRetryDelayMs(
          "upstream_rate_limited",
          retries,
          2_147_483_000,
          () => random,
        ),
      );
      expect(new Set(delays).size).toBe(delays.length);
      for (const delay of delays) {
        expect(delay).toBeGreaterThanOrEqual(60_000);
        expect(delay).toBeLessThan(120_000);
      }
    },
  );

  it.each([
    ["upstream_stream_terminated", 0, 5_000],
    ["upstream_connection_error", 1, 5_000],
    ["upstream_timeout", 2, undefined],
    ["upstream_provider_failure", 2, undefined],
    ["upstream_rate_limited", 4, undefined],
    ["task_spend_limit", 0, undefined],
    ["agent_error", 0, undefined],
  ] as const)(
    "bounds retries for %s after %i retries",
    (classification, retries, expected) => {
      expect(upstreamTurnRetryDelayMs(classification, retries)).toBe(expected);
    },
  );
});
