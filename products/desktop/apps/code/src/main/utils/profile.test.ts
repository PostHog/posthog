import { describe, expect, it } from "vitest";
import {
  defaultCdpPort,
  InvalidProfileError,
  profileSuffix,
  resolveProfile,
} from "./profile";

describe("dev profiles", () => {
  it.each([
    { name: "no profile requested", argv: [], env: {}, expected: null },
    {
      name: "env var",
      argv: [],
      env: { POSTHOG_CODE_PROFILE: "alice" },
      expected: "alice",
    },
    {
      name: "argv flag",
      argv: ["--posthog-profile=bob"],
      env: {},
      expected: "bob",
    },
    {
      name: "argv flag wins over env var",
      argv: ["--posthog-profile=bob"],
      env: { POSTHOG_CODE_PROFILE: "alice" },
      expected: "bob",
    },
    {
      name: "empty env var is treated as unset",
      argv: [],
      env: { POSTHOG_CODE_PROFILE: "  " },
      expected: null,
    },
    {
      name: "normalizes case and separators",
      argv: ["--posthog-profile=Test User_2"],
      env: {},
      expected: "test-user-2",
    },
  ])("resolves $name", ({ argv, env, expected }) => {
    expect(resolveProfile(argv, env, true)).toBe(expected);
  });

  it("ignores profiles in a packaged build", () => {
    expect(resolveProfile([], { POSTHOG_CODE_PROFILE: "alice" }, false)).toBe(
      null,
    );
  });

  it.each([
    { name: "a name with no letters or digits", requested: "!!!" },
    { name: "a name over the length cap", requested: "a".repeat(25) },
  ])("rejects $name rather than falling back", ({ requested }) => {
    expect(() =>
      resolveProfile([], { POSTHOG_CODE_PROFILE: requested }, true),
    ).toThrow(InvalidProfileError);
  });

  it("suffixes nothing for the default profile", () => {
    expect(profileSuffix(null)).toBe("");
    expect(profileSuffix("alice")).toBe("-profile-alice");
  });

  it("gives each profile a distinct, stable CDP port", () => {
    expect(defaultCdpPort(null)).toBe(9222);
    expect(defaultCdpPort("alice")).toBe(defaultCdpPort("alice"));
    expect(defaultCdpPort("alice")).not.toBe(defaultCdpPort("bob"));
    expect(defaultCdpPort("alice")).toBeGreaterThan(9222);
  });
});
