import {
  ArchiveIcon,
  CheckCircleIcon,
  GitMergeIcon,
  GitPullRequestIcon,
} from "@phosphor-icons/react";
import { humanizeIdentifier } from "@posthog/core/inbox/activityLog";
import {
  deriveHeadline,
  humanizeReportTitle,
  parseConventionalCommitTitle,
  parsePrUrl,
} from "@posthog/core/inbox/reportPresentation";
import type { SignalReport } from "@posthog/shared/types";
import { ConventionalCommitScopeTag } from "@posthog/ui/features/inbox/components/ConventionalCommitScopeTag";
import { InboxMetaSourceStack } from "@posthog/ui/features/inbox/components/InboxMetaSourceStack";
import { SignalReportPriorityBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportPriorityBadge";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import type { HTMLAttributes, ReactNode } from "react";

export interface InboxReportRowViewProps {
  report: SignalReport;
  reviewers?: ReactNode;
  restoreAction?: ReactNode;
  prefetchHandlers?: Pick<
    HTMLAttributes<HTMLDivElement>,
    "onPointerEnter" | "onPointerLeave" | "onFocus" | "onBlur"
  >;
  onOpen: () => void;
  onOpenPr: (url: string) => void;
}

export function InboxReportRowView({
  report,
  reviewers,
  restoreAction,
  prefetchHandlers,
  onOpen,
  onOpenPr,
}: InboxReportRowViewProps): React.JSX.Element {
  const conventionalTitle = parseConventionalCommitTitle(report.title);
  const headline = deriveHeadline(report.summary);
  const prUrl = report.implementation_pr_url ?? null;
  const pr = prUrl ? parsePrUrl(prUrl) : null;
  const isTerminal =
    report.status === "resolved" || report.status === "suppressed";

  return (
    // biome-ignore lint/a11y/useSemanticElements: The row contains independent PR and restore buttons.
    <div
      role="button"
      tabIndex={0}
      {...prefetchHandlers}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
      className={`flex w-full cursor-pointer items-center gap-3 rounded-(--radius-2) border bg-(--color-panel-solid) px-3 py-2 text-left transition-[background-color,border-color,opacity] duration-150 hover:border-(--gray-9) hover:bg-(--gray-2) focus-visible:border-(--gray-9) focus-visible:bg-(--gray-2) focus-visible:outline-none ${pr ? "border-(--gray-6) border-solid" : "border-(--gray-6) border-dashed"} ${isTerminal ? "opacity-55 hover:opacity-100 focus-visible:opacity-100" : ""}`}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate font-medium text-[14px] text-gray-12">
          {conventionalTitle && (
            <ConventionalCommitScopeTag
              type={conventionalTitle.type}
              scope={conventionalTitle.scope}
            />
          )}
          <span>{humanizeReportTitle(report.title, "Untitled report")}</span>
        </span>
        {headline && (
          <span className="line-clamp-2 text-[13px] text-gray-11">
            {headline}
          </span>
        )}
        <span className="flex items-center gap-1.5 text-[12.5px] text-gray-10">
          <InboxMetaSourceStack sourceProducts={report.source_products} />
          <RelativeTimestamp
            timestamp={report.created_at}
            className="shrink-0 text-[12.5px]"
          />
        </span>
      </div>
      <span className="flex shrink-0 items-center gap-2">
        {report.status === "resolved" && (
          <span
            title="The fix shipped and this report closed"
            className="flex items-center gap-1 rounded border border-(--green-6) bg-(--green-2) px-1.5 py-0.5 text-[12px] text-green-11"
          >
            <CheckCircleIcon size={11} />
            Shipped
          </span>
        )}
        {report.status === "suppressed" && (
          <span
            title={report.dismissal_note ?? undefined}
            className="flex items-center gap-1 rounded border border-(--gray-6) bg-(--gray-2) px-1.5 py-0.5 text-[12px] text-gray-11"
          >
            <ArchiveIcon size={11} />
            Archived
            {report.dismissal_reason
              ? ` · ${humanizeIdentifier(report.dismissal_reason)}`
              : ""}
          </span>
        )}
        {reviewers}
        <SignalReportPriorityBadge priority={report.priority} />
        {/* biome-ignore lint/a11y/noStaticElementInteractions: This span only stops nested controls from opening the row. */}
        <span
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
          className="flex items-center gap-1.5"
        >
          {pr && prUrl && (
            <button
              type="button"
              onClick={() => onOpenPr(prUrl)}
              title={
                report.implementation_pr_merged
                  ? "This report's earlier PR merged, but evidence kept arriving"
                  : "Open the pull request on GitHub"
              }
              className={
                report.implementation_pr_merged
                  ? "flex items-center gap-1 rounded border border-(--gray-6) px-1.5 py-0.5 font-mono text-[12px] text-gray-11 hover:bg-(--gray-3) hover:text-gray-12"
                  : "flex items-center gap-1 rounded border border-(--accent-7) bg-(--accent-2) px-1.5 py-0.5 font-mono text-(--accent-11) text-[12px] hover:bg-(--accent-3)"
              }
            >
              {report.implementation_pr_merged ? (
                <GitMergeIcon size={11} />
              ) : (
                <GitPullRequestIcon size={11} />
              )}
              #{pr.number}
              {report.implementation_pr_merged ? " merged" : ""}
            </button>
          )}
          {restoreAction}
        </span>
      </span>
    </div>
  );
}
