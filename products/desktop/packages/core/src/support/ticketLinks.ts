import type { SupportTicket } from "@posthog/api-client/posthog-client";

export function slackThreadUrl(
  ticket: Pick<SupportTicket, "slack_channel_id" | "slack_thread_ts">,
): string | null {
  if (!ticket.slack_channel_id || !ticket.slack_thread_ts) {
    return null;
  }
  const ts = ticket.slack_thread_ts.replace(".", "");
  return `https://app.slack.com/archives/${ticket.slack_channel_id}/p${ts}`;
}

export function githubIssueUrl(
  ticket: Pick<SupportTicket, "github_repo" | "github_issue_number">,
): string | null {
  if (!ticket.github_repo || !ticket.github_issue_number) {
    return null;
  }
  return `https://github.com/${ticket.github_repo}/issues/${ticket.github_issue_number}`;
}
