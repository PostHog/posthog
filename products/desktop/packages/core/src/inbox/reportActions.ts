import { buildDiscussReportPrompt as buildSharedDiscussReportPrompt } from "@posthog/shared";
import { buildInboxDeeplink } from "@posthog/shared/deeplink";
import type { SignalReport } from "@posthog/shared/types";

/**
 * Should the Create PR action be offered on this report?
 *
 * Mirrors the server-side autostart rules: only when the report is ready and
 * actually actionable, or when it's blocked on user input the user can supply.
 * Hidden once an implementation PR exists or the issue is already fixed.
 */
export function canCreateImplementationPr(report: SignalReport): boolean {
  if (report.implementation_pr_url) return false;
  if (report.already_addressed === true) return false;
  if (report.status === "pending_input") return true;
  if (report.status === "ready") {
    return (
      report.actionability === "immediately_actionable" ||
      report.actionability === "requires_human_input"
    );
  }
  return false;
}

interface BuildCreatePrReportPromptOptions {
  reportId: string;
  /**
   * Canonical web URL of the report
   * (`https://<region>.posthog.com/project/<projectId>/inbox/<reportId>`).
   * Embedded as a clickable backlink so the agent can reference the report from
   * the cloud PR. Prefer this over the desktop `posthog-code://` deep link,
   * which isn't navigable from GitHub or Slack. Omitted when the region/project
   * aren't known.
   */
  reportUrl?: string | null;
  feedback?: string;
}

export function buildCreatePrReportPrompt({
  reportId,
  reportUrl,
  feedback,
}: BuildCreatePrReportPromptOptions): string {
  const reportRef = reportUrl
    ? `${reportId} ([inbox item](${reportUrl}))`
    : reportId;
  const base = `Act on PostHog inbox report ${reportRef}. Use the inbox MCP tools to fetch the report, its contributing findings, any suggested reviewers, and any implementation PR already linked to it; investigate the root cause; and implement the fix.\n\nIf the report already has a linked implementation PR (check the report's \`implementation_pr_url\`) and it is still open, you are iterating on existing work: check that PR out with \`gh pr checkout <url>\`, continue on its branch, and commit your changes to that same PR. Do NOT open a second PR for the same fix. Otherwise, open a PR. Only open a separate PR alongside an existing one when the user's feedback clearly asks for a distinct change.\n\nIf you can't fetch the report, stop and report that instead of guessing what it contains.`;
  const trimmedFeedback = feedback?.trim();
  if (!trimmedFeedback) return base;
  return `${base}\n\nAdditional feedback from the user (take this into account, including any questions raised in the report thread):\n${trimmedFeedback}`;
}

interface BuildDiscussReportPromptOptions {
  reportId: string;
  reportTitle?: string | null;
  question?: string;
  isDevBuild: boolean;
}

export function buildDiscussReportPrompt({
  reportId,
  reportTitle,
  question,
  isDevBuild,
}: BuildDiscussReportPromptOptions): string {
  const reportLink = buildInboxDeeplink(reportId, reportTitle, { isDevBuild });
  return buildSharedDiscussReportPrompt({ reportId, reportLink, question });
}
