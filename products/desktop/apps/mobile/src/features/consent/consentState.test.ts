import { describe, expect, it } from "vitest";
import { deriveOrgConsent, type OrgConsentInputs } from "./consentState";

describe("deriveOrgConsent", () => {
  const org = (approved: boolean | undefined) => ({
    is_ai_data_processing_approved: approved,
  });

  it.each<{
    name: string;
    inputs: OrgConsentInputs;
    expected: ReturnType<typeof deriveOrgConsent>;
  }>([
    {
      name: "loading while the user has not resolved",
      inputs: {
        organization: undefined,
        betaTermsAccepted: undefined,
        hasError: false,
      },
      expected: { status: "loading" },
    },
    {
      name: "loading while beta terms are still pending",
      inputs: {
        organization: org(true),
        betaTermsAccepted: undefined,
        hasError: false,
      },
      expected: { status: "loading" },
    },
    {
      name: "error takes priority over loaded data",
      inputs: {
        organization: org(true),
        betaTermsAccepted: true,
        hasError: true,
      },
      expected: { status: "error" },
    },
    {
      name: "both requirements unmet",
      inputs: {
        organization: org(false),
        betaTermsAccepted: false,
        hasError: false,
      },
      expected: {
        status: "resolved",
        needsAiConsent: true,
        needsBetaTerms: true,
        satisfied: false,
      },
    },
    {
      name: "only beta terms unmet",
      inputs: {
        organization: org(true),
        betaTermsAccepted: false,
        hasError: false,
      },
      expected: {
        status: "resolved",
        needsAiConsent: false,
        needsBetaTerms: true,
        satisfied: false,
      },
    },
    {
      name: "only AI consent unmet",
      inputs: {
        organization: org(false),
        betaTermsAccepted: true,
        hasError: false,
      },
      expected: {
        status: "resolved",
        needsAiConsent: true,
        needsBetaTerms: false,
        satisfied: false,
      },
    },
    {
      name: "both requirements satisfied",
      inputs: {
        organization: org(true),
        betaTermsAccepted: true,
        hasError: false,
      },
      expected: {
        status: "resolved",
        needsAiConsent: false,
        needsBetaTerms: false,
        satisfied: true,
      },
    },
  ])("returns $name", ({ inputs, expected }) => {
    expect(deriveOrgConsent(inputs)).toEqual(expected);
  });
});
