export interface TeamFlowEligibility {
  isAdmin: boolean | null;
  projectHasTeamIntegration: boolean | null;
  cloudRegion: string | null;
}

export function computeShouldUseTeamFlow(
  eligibility: TeamFlowEligibility,
): boolean {
  return (
    eligibility.isAdmin === true &&
    eligibility.projectHasTeamIntegration === false &&
    eligibility.cloudRegion != null
  );
}

export function validateInstallUrl(
  installUrl: string | null | undefined,
): string {
  const trimmed = installUrl?.trim() ?? "";
  if (!trimmed) {
    throw new Error("GitHub connection did not return a URL");
  }
  return trimmed;
}
