import {
  deriveHeadline,
  humanizeReportTitle,
  parsePrUrl,
} from "@posthog/core/inbox/reportPresentation";
import { AutocompleteItem, Button, cn } from "@posthog/quill";
import { formatRelativeAge } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/types";
import { InboxReportContextMenu } from "@posthog/ui/features/inbox/components/InboxReportContextMenu";
import { PriorityMonogram } from "@posthog/ui/features/inbox/components/PriorityMonogram";
import { useInboxReportDetailPrefetch } from "@posthog/ui/features/inbox/hooks/useInboxReportDetailPrefetch";
import { useInboxReportReadState } from "@posthog/ui/features/inbox/hooks/useInboxReportReadState";
import { navigateToInboxReportDetail } from "@posthog/ui/router/navigationBridge";
import type { ReactElement } from "react";

/** One report in the rail's Self-driving list. */
export function InboxPaneRow({
  report,
  isSelected,
  optionValue,
}: {
  report: SignalReport;
  isSelected: boolean;
  optionValue: string;
}): ReactElement {
  const { isUnread, enabled, setRead } = useInboxReportReadState(report.id);
  const { pointerHandlers } = useInboxReportDetailPrefetch({
    to: "/reports/$reportId",
    params: { reportId: report.id },
  });
  const title = humanizeReportTitle(report.title, "Untitled report");
  // The same lead sentence the page rows show, clamped to two lines here. The
  // row is a button, whose wrapper truncates on one line, so the preview has to
  // opt back into wrapping.
  const headline = deriveHeadline(report.summary);
  const pr = report.implementation_pr_url
    ? parsePrUrl(report.implementation_pr_url)
    : null;

  return (
    <InboxReportContextMenu report={report}>
      <div className="group/report-row relative">
        <AutocompleteItem
          value={optionValue}
          nativeButton
          aria-label={
            report.priority
              ? `${title}, priority ${report.priority}`
              : `${title}, priority unknown`
          }
          className={cn(
            "h-auto w-full items-start py-1.5 pr-8 text-left ring-offset-0 data-highlighted:border-transparent data-highlighted:bg-fill-hover data-highlighted:ring-0 [&>span]:w-full [&>span]:items-start [&>span]:gap-2",
            isSelected && "bg-fill-selected",
          )}
          onClick={() => navigateToInboxReportDetail(report.id)}
          {...pointerHandlers}
        >
          <span className="mt-0.5 shrink-0">
            <PriorityMonogram priority={report.priority} />
          </span>
          <span className="min-w-0 flex-1">
            <span
              className={cn(
                "block truncate text-[13px]",
                isUnread ? "font-semibold" : "font-medium",
              )}
            >
              {title}
            </span>
            {headline && (
              <span className="line-clamp-2 whitespace-normal text-[12px] text-muted-foreground leading-snug">
                {headline}
              </span>
            )}
            <span className="mt-1 block truncate text-muted-foreground/70 text-xxs">
              {formatRelativeAge(report.created_at)}
              {pr ? ` · ${pr.repoSlug}` : ""}
            </span>
          </span>
        </AutocompleteItem>
        {enabled && (
          <Button
            variant="default"
            size="icon-sm"
            className={cn(
              "absolute top-1 right-0.5",
              !isUnread &&
                "opacity-0 focus-visible:opacity-100 group-focus-within/report-row:opacity-100 group-hover/report-row:opacity-100",
            )}
            aria-label={
              isUnread ? "Mark report as read" : "Mark report as unread"
            }
            title={isUnread ? "Unread. Mark as read" : "Mark as unread"}
            onClick={() => setRead(isUnread)}
          >
            <span
              className={cn(
                "size-2 rounded-full",
                isUnread ? "bg-(--blue-9)" : "border border-(--gray-9)",
              )}
            />
          </Button>
        )}
      </div>
    </InboxReportContextMenu>
  );
}
