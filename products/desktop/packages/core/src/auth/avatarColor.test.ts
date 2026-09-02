import { describe, expect, it } from "vitest";
import { avatarColor } from "./avatarColor";

describe("avatarColor", () => {
  it("is deterministic for a given seed", () => {
    expect(avatarColor("user-uuid-123")).toEqual(avatarColor("user-uuid-123"));
  });

  it("returns a paired bg/text hex color", () => {
    for (const seed of ["a", "raquel@posthog.com", "uuid", "", "James Doe"]) {
      const color = avatarColor(seed);
      expect(color.bg).toMatch(/^#[0-9a-f]{6}$/);
      expect(color.text).toMatch(/^#[0-9a-f]{6}$/);
    }
  });

  it("spreads distinct seeds across more than one color", () => {
    const seeds = Array.from({ length: 40 }, (_, i) => `person-${i}`);
    const distinct = new Set(seeds.map((s) => avatarColor(s).bg));
    expect(distinct.size).toBeGreaterThan(1);
  });
});
