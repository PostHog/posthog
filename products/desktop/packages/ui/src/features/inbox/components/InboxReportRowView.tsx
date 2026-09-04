import {
  CheckCircleIcon,
  GitMergeIcon,
  GitPullRequestIcon,
} from "@phosphor-icons/react";
import {
  deriveHeadline,
  humanizeReportTitle,
  parseConventionalCommitTitle,
  parsePrUrl,
} from "@posthog/core/inbox/reportPresentation";
import { dismissalReasonLabel } from "@posthog/shared/dismissalReasons";
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
  const isShipped =
    report.status === "resolved" &&
    (report.implementation_pr_merged === true ||
      report.dismissal_reason === "pr_merged");
  const borderClass =
    pr || report.status === "resolved"
      ? "border-(--gray-6) border-solid hover:border-(--accent-9) focus-visible:border-(--accent-9)"
      : "border-(--gray-6) border-dotted hover:border-(--accent-9) focus-visible:border-(--accent-9)";

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
      className={`flex w-full cursor-pointer items-center gap-3 rounded-(--radius-2) border bg-(--color-panel-solid) px-3 py-2 text-left transition-[background-color,border-color,box-shadow,opacity] duration-150 hover:bg-(--gray-3) hover:shadow-sm focus-visible:bg-(--gray-3) focus-visible:outline-none focus-visible:ring-(--gray-8) focus-visible:ring-1 ${borderClass} ${isTerminal ? "opacity-55 hover:opacity-100 focus-visible:opacity-100" : ""}`}
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
        <span className="flex min-w-0 items-center gap-1.5 overflow-hidden text-[12.5px] text-gray-10">
          {pr && (
            <span title={pr.repoSlug} className="max-w-48 truncate font-medium">
              {pr.repoSlug}
            </span>
          )}
          <InboxMetaSourceStack sourceProducts={report.source_products} />
          {report.status === "suppressed" && (
            <span
              title={report.dismissal_note ?? undefined}
              className="flex min-w-0 items-center gap-1.5"
            >
              <span className="size-1.5 shrink-0 rounded-full bg-(--red-9)" />
              <span className="truncate">
                {report.dismissal_reason
                  ? dismissalReasonLabel(report.dismissal_reason)
                  : "Archived"}
              </span>
            </span>
          )}
          {report.status === "resolved" &&
            !isShipped &&
            report.dismissal_reason && (
              <span
                title={report.dismissal_note ?? undefined}
                className="flex min-w-0 items-center gap-1.5"
              >
                <span className="size-1.5 shrink-0 rounded-full bg-(--green-9)" />
                <span className="truncate">
                  {dismissalReasonLabel(report.dismissal_reason)}
                </span>
              </span>
            )}
          <RelativeTimestamp
            timestamp={report.created_at}
            className="shrink-0 text-[12.5px]"
          />
        </span>
      </div>
      <span className="flex shrink-0 items-center gap-2">
        {report.status === "resolved" &&
          (isShipped ? (
            <span
              title="The fix shipped and this report closed"
              className="flex items-center gap-1 rounded border border-(--green-6) bg-(--green-2) px-1.5 py-0.5 text-[12px] text-green-11"
            >
              <CheckCircleIcon size={11} />
              Shipped
            </span>
          ) : (
            <span
              title={
                report.dismissal_note ||
                (report.dismissal_reason
                  ? `Resolved: ${dismissalReasonLabel(report.dismissal_reason)}`
                  : "This report was resolved")
              }
              className="flex items-center gap-1 rounded border border-(--gray-6) bg-(--gray-2) px-1.5 py-0.5 text-[12px] text-gray-11"
            >
              <CheckCircleIcon size={11} />
              Resolved
            </span>
          ))}
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
