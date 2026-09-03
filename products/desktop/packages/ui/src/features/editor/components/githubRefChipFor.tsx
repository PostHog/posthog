import { GithubPrRefChip } from "@posthog/ui/features/editor/components/GithubPrRefChip";
import { GithubRefChip } from "@posthog/ui/features/editor/components/GithubRefChip";
import { parseGithubIssueUrl } from "@posthog/ui/features/message-editor/githubIssueUrl";
import type { ReactElement, ReactNode } from "react";

/**
 * The chip a markdown link to GitHub renders as, or null when the link points
 * somewhere else. Shared so both markdown renderers route references the same
 * way.
 */
export function githubRefChipFor(
  href: string | undefined,
  children: ReactNode,
): ReactElement | null {
  const githubRef = href ? parseGithubIssueUrl(href) : null;
  if (!githubRef) return null;

  // A bare URL reads as noise in a sentence, so it becomes owner/repo#number.
  const isAutoLink = typeof children === "string" && children === href;
  const label =
    isAutoLink && githubRef.isReviewComment
      ? `Comment on PR #${githubRef.number}`
      : isAutoLink
        ? `${githubRef.owner}/${githubRef.repo}#${githubRef.number}`
        : children;

  if (githubRef.kind === "pr") {
    return (
      <GithubPrRefChip href={githubRef.normalizedUrl}>{label}</GithubPrRefChip>
    );
  }
  return (
    <GithubRefChip href={githubRef.normalizedUrl} kind="issue">
      {label}
    </GithubRefChip>
  );
}
