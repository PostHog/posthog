export interface ConsentRequirement {
  organizationId: string;
  required: boolean;
  needsAiConsent: boolean;
  needsBetaTerms: boolean;
}

export function sampleConsentRequirement(
  current: ConsentRequirement | undefined,
  organizationId: string,
  needsAiConsent: boolean,
  needsBetaTerms: boolean,
): ConsentRequirement {
  if (current?.organizationId === organizationId) return current;
  return {
    organizationId,
    required: needsAiConsent || needsBetaTerms,
    needsAiConsent,
    needsBetaTerms,
  };
}
