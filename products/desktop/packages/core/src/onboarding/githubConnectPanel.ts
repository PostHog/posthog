import type { OnboardingGithubConnectFlow } from "@posthog/shared/analytics-events";
import {
  GITHUB_CONNECT_TIMEOUT_MESSAGE,
  GITHUB_INSTALL_PENDING_MESSAGE,
  isGithubConnectPendingApproval,
} from "../integrations/connectErrors";
import { POSTHOG_GITHUB_APP_URL } from "../integrations/githubApp";

export interface GithubPanelMessageOptions {
  hasConnectError: boolean;
  connectErrorMessage: string;
  timedOut: boolean;
  isConnecting: boolean;
  /** GitHub is waiting on an org owner to approve the install. */
  isPending?: boolean;
}

/** Null when the connect flow has nothing to report, so the line stays out. */
export function getGithubPanelMessage(
  options: GithubPanelMessageOptions,
): string | null {
  if (options.hasConnectError) return options.connectErrorMessage;
  if (options.isPending) return GITHUB_INSTALL_PENDING_MESSAGE;
  if (options.timedOut) {
    return GITHUB_CONNECT_TIMEOUT_MESSAGE;
  }
  return null;
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

export interface ConnectAbandonedInputs {
  flowType: OnboardingGithubConnectFlow;
  startedAtMs: number;
  nowMs: number;
}

export interface ConnectAbandonedProps {
  flow_type: OnboardingGithubConnectFlow;
  seconds_since_started: number;
}

export function buildConnectAbandonedProps(
  inputs: ConnectAbandonedInputs,
): ConnectAbandonedProps {
  return {
    flow_type: inputs.flowType,
    seconds_since_started: Math.max(
      0,
      Math.round((inputs.nowMs - inputs.startedAtMs) / 1000),
    ),
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
      : "Sign in with GitHub";
  return { isRetry, shouldReset: inputs.hasConnectError, label };
}

export type GithubApprovalState = "none" | "awaiting" | "approved";

export interface GithubInstallRequestSummary {
  status: "pending" | "approved" | "unidentified";
}

export interface DeriveGithubApprovalStateInputs {
  errorCode: string | null | undefined;
  requests: GithubInstallRequestSummary[];
  hasIntegration: boolean;
}

/** Reads the durable server-side "awaiting org owner approval" state (see
 * `GitHubInstallRequest` on the backend), plus the in-flight callback error so the
 * panel shows the wait immediately after the redirect, before the request list
 * has had a chance to refetch. An existing integration always wins: once linked,
 * any leftover request rows are stale history, not current state. */
export function deriveGithubApprovalState(
  inputs: DeriveGithubApprovalStateInputs,
): GithubApprovalState {
  if (inputs.hasIntegration) return "none";
  if (isGithubConnectPendingApproval(inputs.errorCode)) return "awaiting";
  if (inputs.requests.some((request) => request.status === "pending")) {
    return "awaiting";
  }
  if (inputs.requests.some((request) => request.status === "approved")) {
    return "approved";
  }
  return "none";
}
