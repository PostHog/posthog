import { requestErrorStatus } from "@posthog/api-client/fetcher";

export interface GithubConnectError {
  message: string;
  code: string | null;
}

export const GITHUB_CONNECT_TIMEOUT_MESSAGE =
  "We didn't hear back from GitHub. If your organization requires approval to install the PostHog app, ask a GitHub org owner to approve it, then connect again.";

export const GITHUB_INSTALL_PENDING_MESSAGE =
  "GitHub sent your request to your organization owners. Once an owner approves the PostHog app, we'll finish connecting here.";

/**
 * A disconnect that 404s means the row is already gone, usually because the App was
 * uninstalled on GitHub and the webhook cleaned up first. That is the outcome the user
 * wanted, so callers treat it as success and refresh rather than surface a failure.
 *
 * A typed error carries its status, so that decides on its own. The message match is only
 * for untyped callers — a 400 body that happens to read "not found" (the blocker names the
 * pipelines and workflows still using the integration) is a real failure.
 */
export function isAlreadyDisconnectedError(error: unknown): boolean {
  const status = requestErrorStatus(error);
  if (status !== undefined) return status === 404;
  return (
    error instanceof Error &&
    /\[404\]|not found|No GitHub integration found/i.test(error.message)
  );
}

export const GITHUB_CONNECT_ERROR_MESSAGES: Record<string, string> = {
  access_denied:
    "You declined access on GitHub. Try again to grant the permissions PostHog needs.",
  github_oauth_error: "GitHub returned an error during sign-in. Please retry.",
  missing_params: "GitHub returned an incomplete response. Please retry.",
  invalid_state:
    "The connection link expired before you finished. Please retry.",
  invalid_installation:
    "This GitHub installation isn't reachable from your account. Try a different account or org.",
  invalid_team:
    "Your project access changed during sign-in. Please retry from the current project.",
  invalid_installation_id:
    "GitHub returned an invalid installation. Please retry.",
  exchange_failed:
    "Couldn't exchange the GitHub authorization code. Please retry.",
  installation_verify_failed:
    "Couldn't verify your access to this GitHub installation. Please retry.",
  installation_not_authorized:
    "Your GitHub account isn't authorized for this installation. Ask the org admin to grant access, or sign in with a different GitHub account.",
  installation_fetch_failed:
    "Couldn't fetch installation details from GitHub. Please retry.",
  installation_token_failed:
    "Couldn't get an access token from GitHub. Please retry.",
  integration_create_failed:
    "Couldn't save the GitHub connection. Please retry.",
  github_install_pending:
    "PostHog needs approval from a GitHub org owner. We sent the request. Until it's approved, your tasks run on your machine. Once it's approved, connect again.",
};

export const GITHUB_CONNECT_PENDING_APPROVAL_CODE = "github_install_pending";

/** Travels on the error channel but is not a failure: the connect can still
 * succeed once an org owner approves, so callers render it as informational. */
export function isGithubConnectPendingApproval(
  code: string | null | undefined,
): boolean {
  return code === GITHUB_CONNECT_PENDING_APPROVAL_CODE;
}

export function describeGithubConnectError(
  error: GithubConnectError | null,
): string {
  if (!error) return "";
  if (error.code && GITHUB_CONNECT_ERROR_MESSAGES[error.code]) {
    return GITHUB_CONNECT_ERROR_MESSAGES[error.code];
  }
  return error.message;
}

/**
 * A message for a failed team-integration disconnect. The backend refuses with a 403 for
 * non-admins and with a validation detail when pipelines or workflows still use the
 * integration; that detail is the actionable part, so it is shown verbatim.
 */
export function describeIntegrationDisconnectError(
  error: unknown,
  fallback: string,
): string {
  if (requestErrorStatus(error) === 403) {
    return "Only project admins can disconnect this integration.";
  }
  const body =
    error && typeof error === "object" && "body" in error
      ? (error as { body?: unknown }).body
      : null;
  const detail =
    body && typeof body === "object" && "detail" in body
      ? (body as { detail?: unknown }).detail
      : null;
  if (typeof detail === "string" && detail) return detail;
  return error instanceof Error ? error.message : fallback;
}
