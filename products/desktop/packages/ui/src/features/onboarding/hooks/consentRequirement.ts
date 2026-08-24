export interface ConsentRequirement {
  organizationId: string;
  required: boolean;
}

export function sampleConsentRequirement(
  current: ConsentRequirement | undefined,
  organizationId: string,
  consentSatisfied: boolean,
): ConsentRequirement {
  if (current?.organizationId === organizationId) return current;
  return { organizationId, required: !consentSatisfied };
}
