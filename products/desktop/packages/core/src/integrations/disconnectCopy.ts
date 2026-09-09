export type GithubDisconnectScope = "project" | "account";

/**
 * Disconnecting the last PostHog reference to a GitHub App installation also uninstalls the App
 * on GitHub and drops every other PostHog link to it, so the dialog states which case applies
 * instead of a generic warning.
 */
export function buildGithubDisconnectDescription(
  accountLabel: string,
  installationShared: boolean,
  scope: GithubDisconnectScope,
): string {
  if (installationShared) {
    const subject =
      scope === "account"
        ? "Your account stops using GitHub."
        : "This project stops using GitHub.";
    return `${subject} The PostHog app stays installed on GitHub because other projects or accounts still use it.`;
  }
  return `This uninstalls the PostHog app from ${accountLabel} on GitHub and disconnects it from every PostHog project and personal account that uses it.`;
}

export const SLACK_DISCONNECT_DESCRIPTION =
  "Reports and notifications from this project stop posting to Slack until someone reconnects it.";
