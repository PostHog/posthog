import { GitlabLogo } from "@phosphor-icons/react";
import type { GitlabMergeRequestRef } from "@posthog/core/git-interaction/prStatus";
import { Button } from "@posthog/quill";
import { PR_TONE_FILL_COMPACT } from "../prTone";

interface MergeRequestBadgeLinkProps {
  url: string;
  mergeRequest: GitlabMergeRequestRef;
  /** Compact pill for the command-center cell header, as a plain anchor. */
  compact?: boolean;
}

/**
 * The "open this merge request on GitLab" badge. Unlike `PRBadgeLink` it has
 * no lifecycle state, because PR state comes from GitHub.
 */
export function MergeRequestBadgeLink({
  url,
  mergeRequest,
  compact = false,
}: MergeRequestBadgeLinkProps) {
  const reference = `!${mergeRequest.iid}`;
  const label = `Open merge request ${reference} on GitLab`;

  if (compact) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={label}
        title={url}
        onClick={(e) => e.stopPropagation()}
        className={`inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px] no-underline ${PR_TONE_FILL_COMPACT.gray}`}
      >
        <GitlabLogo size={10} weight="bold" />
        <span>MR {reference}</span>
      </a>
    );
  }

  return (
    <Button
      size="sm"
      variant="outline"
      render={
        // biome-ignore lint/a11y/useAnchorContent: the content is the button's children, across a render prop the rule can't follow, and `aria-label` names it anyway
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          title={url}
          aria-label={label}
          onClick={(e) => e.stopPropagation()}
        />
      }
      className="no-underline"
    >
      <GitlabLogo weight="bold" />
      <span>MR {reference}</span>
    </Button>
  );
}
