export interface GithubConnectError {
  message: string;
  code: string | null;
}

export const GITHUB_CONNECT_TIMEOUT_MESSAGE =
  "We didn't hear back from GitHub. If your organization requires approval to install the PostHog app, ask a GitHub org owner to approve it, then connect again.";

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
};

export function describeGithubConnectError(
  error: GithubConnectError | null,
): string {
  if (!error) return "";
  if (error.code && GITHUB_CONNECT_ERROR_MESSAGES[error.code]) {
    return GITHUB_CONNECT_ERROR_MESSAGES[error.code];
  }
  return error.message;
}
