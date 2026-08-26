export type OrgConsent =
  | { status: "loading" }
  | { status: "error" }
  | {
      status: "resolved";
      needsAiConsent: boolean;
      needsBetaTerms: boolean;
      satisfied: boolean;
    };

export interface OrgConsentInputs {
  organization: { is_ai_data_processing_approved?: boolean } | undefined;
  betaTermsAccepted: boolean | undefined;
  hasError: boolean;
}

export function deriveOrgConsent({
  organization,
  betaTermsAccepted,
  hasError,
}: OrgConsentInputs): OrgConsent {
  if (hasError) {
    return { status: "error" };
  }
  if (!organization || betaTermsAccepted === undefined) {
    return { status: "loading" };
  }

  const needsAiConsent = organization.is_ai_data_processing_approved !== true;
  const needsBetaTerms = !betaTermsAccepted;
  return {
    status: "resolved",
    needsAiConsent,
    needsBetaTerms,
    satisfied: !needsAiConsent && !needsBetaTerms,
  };
}
