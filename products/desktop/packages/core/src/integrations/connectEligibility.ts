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

export type GithubConnectOutcomeKind =
  | "success"
  | "pending_org_approval"
  | "not_authorized"
  | "error";

/**
 * GitHub answers a member's install attempt with `setup_action=request` when an org owner has to
 * approve it. PostHog relays that as the `github_install_pending` code, which is a waiting state
 * rather than a failure, so it must not land in the generic error branch.
 */
export function classifyGithubCallback(
  errorCode: string | null | undefined,
): GithubConnectOutcomeKind {
  if (!errorCode) return "success";
  if (errorCode === "github_install_pending") return "pending_org_approval";
  if (errorCode === "installation_not_authorized") return "not_authorized";
  return "error";
}
