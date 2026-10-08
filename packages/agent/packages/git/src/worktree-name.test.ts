import { describe, expect, it } from "vitest";
import { generateHumanReadableName } from "./worktree-name";

describe("generateHumanReadableName", () => {
  it("returns a string matching adjective-noun-NN", () => {
    const name = generateHumanReadableName();
    expect(name).toMatch(/^[a-z]+-[a-z]+-\d{2}$/);
  });

  it("produces varied names over many calls", () => {
    const names = new Set<string>();
    for (let i = 0; i < 50; i++) {
      names.add(generateHumanReadableName());
    }
    // With 36 * 36 * 90 = ~116k combinations, 50 draws should yield
    // many unique values. Allow generous slack for randomness.
    expect(names.size).toBeGreaterThan(20);
  });

  const samples = Array.from({ length: 25 }, () => generateHumanReadableName());

  it.each(samples)("uses only filesystem-safe characters: %s", (name) => {
    expect(name).toMatch(/^[a-z0-9-]+$/);
  });

  it.each(samples)("stays compact (≤32 chars): %s", (name) => {
    expect(name.length).toBeLessThanOrEqual(32);
  });
});
