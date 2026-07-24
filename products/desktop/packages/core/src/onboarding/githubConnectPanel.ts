import { GITHUB_CONNECT_TIMEOUT_MESSAGE } from "../integrations/connectErrors";
import { POSTHOG_GITHUB_APP_URL } from "../integrations/githubApp";

export interface GithubPanelMessageOptions {
  hasConnectError: boolean;
  connectErrorMessage: string;
  timedOut: boolean;
  isConnecting: boolean;
}

export function getGithubPanelMessage(
  options: GithubPanelMessageOptions,
): string {
  if (options.hasConnectError) return options.connectErrorMessage;
  if (options.timedOut) {
    return GITHUB_CONNECT_TIMEOUT_MESSAGE;
  }
  if (options.isConnecting) return "Waiting for GitHub...";
  return "Unlocks cloud runs, branch pushes, and PR review on this account.";
}

export function resolveSelectedProjectId(
  manuallySelectedProjectId: number | null,
  currentProjectId: number | null | undefined,
  projects: { id: number }[],
): number | null {
  if (manuallySelectedProjectId !== null) return manuallySelectedProjectId;
  return currentProjectId ?? projects[0]?.id ?? null;
}

export function deriveAlternativeConnectedProjects<
  TProject extends { id: number },
>(
  hasGitIntegration: boolean,
  projectsWithGithub: TProject[],
  selectedProjectId: number | null,
): TProject[] {
  if (hasGitIntegration) return [];
  if (!projectsWithGithub.length) return [];
  return projectsWithGithub.filter(
    (project) => project.id !== selectedProjectId,
  );
}

export interface GithubInstallationAccount {
  name?: string | null;
  type?: string | null;
}

export function isAnyIntegrationStale(
  integrations: { installation_id: string }[],
  failedInstallationIds: string[],
): boolean {
  return integrations.some((integration) =>
    failedInstallationIds.includes(integration.installation_id),
  );
}

export function buildInstallationSettingsUrl(
  account: GithubInstallationAccount | null | undefined,
  installationId: string,
): string {
  if (account?.type?.toLowerCase() === "organization") {
    return POSTHOG_GITHUB_APP_URL;
  }
  return `https://github.com/settings/installations/${installationId}`;
}

export interface ConnectFailureInputs {
  hasConnectError: boolean;
  timedOut: boolean;
  errorCode: string | null | undefined;
}

export function buildConnectFailureFingerprint(
  inputs: ConnectFailureInputs,
): string | null {
  if (!inputs.hasConnectError && !inputs.timedOut) return null;
  if (inputs.timedOut) return "timeout";
  return inputs.errorCode ?? "error";
}

export interface ConnectFailedProps {
  reason: "timeout" | "error";
  error_type?: string;
}

export function buildConnectFailedProps(
  inputs: ConnectFailureInputs,
): ConnectFailedProps {
  return {
    reason: inputs.timedOut ? "timeout" : "error",
    error_type: inputs.errorCode ?? undefined,
  };
}

export interface ConnectButtonState {
  isRetry: boolean;
  shouldReset: boolean;
  label: string;
}

export function deriveConnectButtonState(inputs: {
  isConnecting: boolean;
  hasConnectError: boolean;
  timedOut: boolean;
}): ConnectButtonState {
  const isRetry = inputs.hasConnectError || inputs.timedOut;
  const label = inputs.isConnecting
    ? "Retry connection"
    : isRetry
      ? "Try again"
      : "Connect GitHub";
  return { isRetry, shouldReset: inputs.hasConnectError, label };
}
