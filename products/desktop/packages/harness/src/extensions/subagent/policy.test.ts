import { describe, expect, it } from "vitest";
import {
  applyModelScope,
  checkModelScope,
  matchesAllowList,
  SubagentPolicyError,
} from "./policy";

describe("matchesAllowList", () => {
  it("matches an exact model key", () => {
    expect(
      matchesAllowList("anthropic/claude-sonnet-4-5", [
        "anthropic/claude-sonnet-4-5",
      ]),
    ).toBe(true);
  });

  it("matches a trailing-glob pattern", () => {
    expect(
      matchesAllowList("anthropic/claude-sonnet-4-5", ["anthropic/*"]),
    ).toBe(true);
    expect(matchesAllowList("openai/gpt-5-mini", ["openai/gpt-5-*"])).toBe(
      true,
    );
  });

  it("does not match outside the allow list", () => {
    expect(matchesAllowList("openai/gpt-4o", ["anthropic/*"])).toBe(false);
  });
});

describe("checkModelScope", () => {
  it("allows everything when there's no allow list configured", () => {
    expect(checkModelScope("anything/whatever", undefined)).toEqual({
      allowed: true,
      enforced: false,
    });
    expect(checkModelScope("anything/whatever", { enforce: true })).toEqual({
      allowed: true,
      enforced: true,
    });
  });

  it("reports enforced+disallowed", () => {
    const check = checkModelScope("openai/gpt-4o", {
      enforce: true,
      allow: ["anthropic/*"],
    });
    expect(check.allowed).toBe(false);
    expect(check.enforced).toBe(true);
    expect(check.reason).toMatch(/not in the configured modelScope/);
  });
});

describe("applyModelScope", () => {
  it("returns undefined (no warning) for an allowed model", () => {
    expect(
      applyModelScope("anthropic/opus", { allow: ["anthropic/*"] }),
    ).toBeUndefined();
  });

  it("returns a warning string for a disallowed model when not enforced", () => {
    const warning = applyModelScope("openai/gpt-4o", {
      allow: ["anthropic/*"],
    });
    expect(warning).toMatch(/not in the configured modelScope/);
  });

  it("throws SubagentPolicyError for a disallowed model when enforced", () => {
    expect(() =>
      applyModelScope("openai/gpt-4o", {
        enforce: true,
        allow: ["anthropic/*"],
      }),
    ).toThrow(SubagentPolicyError);
  });
});
