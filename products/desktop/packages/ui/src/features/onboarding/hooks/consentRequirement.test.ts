import { describe, expect, it } from "vitest";
import { sampleConsentRequirement } from "./consentRequirement";

describe("sampleConsentRequirement", () => {
  it("keeps a required consent step after the organization accepts", () => {
    const initial = sampleConsentRequirement(undefined, "org-1", true, false);

    expect(sampleConsentRequirement(initial, "org-1", false, false)).toBe(
      initial,
    );
    expect(initial.required).toBe(true);
    expect(initial.needsAiConsent).toBe(true);
  });

  it("samples consent again when the organization changes", () => {
    const initial = sampleConsentRequirement(undefined, "org-1", false, false);
    const switched = sampleConsentRequirement(initial, "org-2", false, true);

    expect(initial.required).toBe(false);
    expect(switched).toEqual({
      organizationId: "org-2",
      required: true,
      needsAiConsent: false,
      needsBetaTerms: true,
    });
  });
});
