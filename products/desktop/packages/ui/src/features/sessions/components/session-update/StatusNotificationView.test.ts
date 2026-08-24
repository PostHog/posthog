import { describe, expect, it } from "vitest";
import {
  formatCompactionFailure,
  formatRetryStatus,
} from "./StatusNotificationView";

describe("formatCompactionFailure", () => {
  it.each([
    {
      error: "Compaction failed: Nothing to compact (session too small)",
      expected: "Compacting failed: Nothing to compact (session too small)",
    },
    {
      error: "Nothing to compact",
      expected: "Compacting failed: Nothing to compact",
    },
    { error: undefined, expected: "Compacting failed" },
  ])("formats $error without duplicate prefixes", ({ error, expected }) => {
    expect(formatCompactionFailure(error)).toBe(expected);
  });
});

describe("formatRetryStatus", () => {
  it.each([
    {
      input: {
        attempt: 1,
        maxAttempts: 3,
        message: "Rate limit reached for gpt-5.6-terra on token ...",
        remainingMs: 0,
      },
      expected: "Rate limit reached. Retrying now (attempt 1 of 3)",
    },
    {
      input: {
        attempt: 2,
        maxAttempts: 3,
        message: "Rate limited",
        remainingMs: 2_000,
      },
      expected: "Rate limit reached. Retrying in 2s (attempt 2 of 3)",
    },
    {
      input: {
        attempt: 2,
        maxAttempts: 3,
        message: "Server overloaded",
        remainingMs: 2_000,
      },
      expected: "Retrying in 2s (attempt 2 of 3)",
    },
  ])("renders a concise retry message", ({ input, expected }) => {
    expect(formatRetryStatus(input)).toBe(expected);
  });
});
