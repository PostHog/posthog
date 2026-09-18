import { ApiRequestError } from "@posthog/api-client/fetcher";
import { describe, expect, it } from "vitest";
import { shouldRetryWikiWrite, wikiWriteRetryDelay } from "./useContextWiki";

describe("context wiki write retry", () => {
  const lockBusy = new ApiRequestError(429, "writer lock busy");

  it.each([
    [0, true],
    [1, true],
    [2, true],
    [3, false],
    [4, false],
  ])(
    "retries a lock-busy 429 only while under the attempt cap (failureCount %i -> %s)",
    (failureCount, expected) => {
      expect(shouldRetryWikiWrite(failureCount, lockBusy)).toBe(expected);
    },
  );

  // A conflict (409) or lint rejection (400) must surface to the caller's
  // banner, not be retried — retrying would mask it and hammer the lock.
  it.each([[409], [400], [404], [500]])(
    "never retries a non-429 status (%i)",
    (status) => {
      expect(shouldRetryWikiWrite(0, new ApiRequestError(status, "x"))).toBe(
        false,
      );
    },
  );

  it.each([
    ["a plain Error", new Error("network down")],
    ["undefined", undefined],
  ])("never retries a non-API error (%s)", (_label, error) => {
    expect(shouldRetryWikiWrite(0, error)).toBe(false);
  });

  it.each([
    [0, 400],
    [1, 800],
    [2, 1200],
  ])(
    "backs off linearly between retries (attempt %i -> %ims)",
    (attempt, ms) => {
      expect(wikiWriteRetryDelay(attempt)).toBe(ms);
    },
  );
});
