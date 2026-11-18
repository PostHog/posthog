import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveSpokenNarration } from "./session-meta";

describe("resolveSpokenNarration", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  // Narration is strictly opt-in: only an explicit `spokenNarration: true`
  // enables it. Cloud/sandbox runs no longer default on, so headless runs
  // (Slack threads, Signals scouts) never load the tool or its instructions.
  it.each([
    {
      name: "explicit true",
      meta: { spokenNarration: true },
      expected: true,
    },
    {
      name: "explicit false",
      meta: { spokenNarration: false },
      expected: false,
    },
    { name: "no meta", meta: undefined, expected: false },
    { name: "empty meta", meta: {}, expected: false },
  ])("resolves $name to $expected outside a sandbox", ({ meta, expected }) => {
    vi.stubEnv("IS_SANDBOX", "");
    expect(resolveSpokenNarration(meta)).toBe(expected);
  });

  it.each([
    { name: "no meta", meta: undefined, expected: false },
    { name: "empty meta", meta: {}, expected: false },
    {
      name: "explicit true",
      meta: { spokenNarration: true },
      expected: true,
    },
    {
      name: "explicit false",
      meta: { spokenNarration: false },
      expected: false,
    },
  ])(
    "resolves $name to $expected in a sandbox (no default-on)",
    ({ meta, expected }) => {
      vi.stubEnv("IS_SANDBOX", "1");
      expect(resolveSpokenNarration(meta)).toBe(expected);
    },
  );
});
