import { describe, expect, it } from "vitest";
import { isEnrichmentEligible } from "./enrichmentEligibility";

describe("isEnrichmentEligible", () => {
  it("accepts supported extensions with content", () => {
    expect(isEnrichmentEligible("src/a.ts", "code")).toBe(true);
    expect(isEnrichmentEligible("src/a.py", "code")).toBe(true);
  });

  it("rejects unsupported extensions", () => {
    expect(isEnrichmentEligible("README.md", "code")).toBe(false);
    expect(isEnrichmentEligible("a.txt", "code")).toBe(false);
  });

  it("rejects empty or missing content", () => {
    expect(isEnrichmentEligible("a.ts", "")).toBe(false);
    expect(isEnrichmentEligible("a.ts", null)).toBe(false);
    expect(isEnrichmentEligible("a.ts", undefined)).toBe(false);
  });

  it("rejects content over the size bound", () => {
    expect(isEnrichmentEligible("a.ts", "x".repeat(1_000_001))).toBe(false);
    expect(isEnrichmentEligible("a.ts", "x".repeat(1_000_000))).toBe(true);
  });
});
