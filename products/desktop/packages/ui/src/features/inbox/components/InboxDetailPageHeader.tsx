import { humanizeReportTitle } from "@posthog/core/inbox/reportPresentation";
import { DetailBackLink } from "@posthog/ui/features/inbox/components/DetailBackLink";
import { InboxMetaRow } from "@posthog/ui/features/inbox/components/InboxMetaRow";
import type { ReactNode } from "react";

interface InboxDetailPageHeaderProps {
  backTo: string;
  backLabel: string;
  breadcrumb?: ReactNode;
  reportTitle: string | null | undefined;
  fallbackTitle: string;
  /** The rare badge that still earns pixels (a non-ready status, For you). */
  badges?: ReactNode;
  /** Inline byline items (source, findings count, timestamp, priority). */
  meta?: ReactNode;
  /** Action button cluster (reviewers, discuss, overflow, dismiss). */
  actions?: ReactNode;
}

/**
 * Compact detail-page header used by all inbox detail screens.
 *
 *   ┌──────────────────────────────────────────────────────────────────────┐
 *   │ ← Back / breadcrumb                                                  │
 *   │ Title                                                                │
 *   │ ───────────────────────────────────────────────────────────────────  │
 *   │ byline (source · signals · time · P2)     [avatars][Discuss][⋯][×]  │
 *   └──────────────────────────────────────────────────────────────────────┘
 *
 * The title renders humanized — conventional-commit prefixes are stripped so a
 * report reads as a brief, not a commit. The bottom row is a muted byline, not
 * a badge rack: taxonomy (priority, actionability) lives there as plain text
 * or not at all.
 */
export function InboxDetailPageHeader({
  backTo,
  backLabel,
  breadcrumb,
  reportTitle,
  fallbackTitle,
  badges,
  meta,
  actions,
}: InboxDetailPageHeaderProps) {
  const displayTitle = humanizeReportTitle(reportTitle, fallbackTitle);
  const hasBottomRow = !!badges || !!meta || !!actions;

  return (
    // Sticky within the detail page's scroll: the title and action verbs stay
    // reachable however deep the reader is in the document.
    <div className="sticky top-0 z-20 flex shrink-0 flex-col gap-3 border-(--gray-5) border-b bg-gray-1 px-6 pt-5 pb-4">
      <div className="flex items-center gap-2 text-[13.5px] text-gray-11">
        <DetailBackLink to={backTo} label={backLabel} />
        {breadcrumb}
      </div>

      <h1 className="min-w-0 font-bold text-[25px] text-gray-12 leading-tight tracking-tight">
        {displayTitle}
      </h1>

      {hasBottomRow && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 text-[13px] text-gray-11">
            {badges}
            {meta && <InboxMetaRow>{meta}</InboxMetaRow>}
          </div>
          {actions && (
            <div className="flex shrink-0 items-center gap-2">{actions}</div>
          )}
        </div>
      )}
    </div>
  );
}
