import {
  ArchiveIcon,
  ArrowCounterClockwiseIcon,
  LightningIcon,
} from "@phosphor-icons/react";
import { extractRepoSelectionRepository } from "@posthog/core/inbox/artefacts";
import {
  deriveHeadline,
  displayConventionalCommitTitle,
  isStatusRedundantWithActionability,
  parseConventionalCommitTitle,
} from "@posthog/core/inbox/reportPresentation";
import { Button } from "@posthog/quill";
import { dismissalReasonLabel } from "@posthog/shared/dismissalReasons";
import type {
  SignalReport,
  SignalReportArtefactsResponse,
} from "@posthog/shared/types";
import { ConventionalCommitScopeTag } from "@posthog/ui/features/inbox/components/ConventionalCommitScopeTag";
import {
  InboxCardActions,
  InboxCardTimestamp,
  inboxCardBodyClassName,
  inboxCardClassName,
} from "@posthog/ui/features/inbox/components/InboxCardChrome";
import { InboxCardSourceMeta } from "@posthog/ui/features/inbox/components/InboxCardSourceMeta";
import { InboxCardTitle } from "@posthog/ui/features/inbox/components/InboxCardTitle";
import { PriorityMonogram } from "@posthog/ui/features/inbox/components/PriorityMonogram";
import { SuggestedReviewerAvatarStack } from "@posthog/ui/features/inbox/components/SuggestedReviewerAvatarStack";
import { ForYouBadge } from "@posthog/ui/features/inbox/components/utils/ForYouBadge";
import { SignalReportActionabilityBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportActionabilityBadge";
import { SignalReportStatusBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportStatusBadge";
import { SignalReportSummaryMarkdown } from "@posthog/ui/features/inbox/components/utils/SignalReportSummaryMarkdown";
import { hasKnownSourceProduct } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { useInboxReportDetailPrefetch } from "@posthog/ui/features/inbox/hooks/useInboxReportDetailPrefetch";
import { useInboxReportArtefacts } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { Button as UiButton } from "@posthog/ui/primitives/Button";
import { Link, useNavigate } from "@tanstack/react-router";
import type { HTMLAttributes, MouseEvent, ReactNode } from "react";

interface ReportCardViewBaseProps {
  report: SignalReport;
  isSelected?: boolean;
  /** Wraps the card body; the container passes the detail-route Link. */
  renderBody: (body: ReactNode, className: string) => ReactNode;
  rootProps?: HTMLAttributes<HTMLDivElement>;
}

interface DefaultReportCardViewProps extends ReportCardViewBaseProps {
  variant?: "default";
  repoSlug?: string | null;
  artefacts: SignalReportArtefactsResponse | null;
  onDismiss?: () => void;
  dismissDisabledReason?: string | null;
  isDismissPending?: boolean;
  onReview?: () => void;
}

/**
 * Archived (suppressed) reports render the same card chrome in a read-only,
 * dimmed state: the triage affordances are replaced by a single Restore action,
 * the metadata row swaps live badges for the archive date + dismissal reason,
 * and the detail link points at the read-only archived view.
 */
interface ArchivedReportCardViewProps extends ReportCardViewBaseProps {
  variant: "archived";
  onRestore?: () => void;
  isRestorePending?: boolean;
}

export type ReportCardViewProps =
  | DefaultReportCardViewProps
  | ArchivedReportCardViewProps;

export function ReportCardView(props: ReportCardViewProps) {
  const { report, isSelected = false, renderBody, rootProps } = props;
  const isArchived = props.variant === "archived";
  // Resolved reports are terminal (their implementation PR merged): shown in the
  // Archive tab for reference, badged as resolved, with no restore action.
  const isResolved = report.status === "resolved";
  const isReady = report.status === "ready";

  const conventionalTitle = parseConventionalCommitTitle(report.title);
  const cardTitle = displayConventionalCommitTitle(
    report.title,
    "Untitled report",
  );
  const headline = deriveHeadline(report.summary);
  const hasSource = hasKnownSourceProduct(report.source_products);
  const reasonLabel =
    isArchived && report.dismissal_reason
      ? dismissalReasonLabel(report.dismissal_reason)
      : null;
  const dismissalNote = report.dismissal_note?.trim() || null;
  const updatedAtRaw = report.updated_at ?? report.created_at;
  const archivedDate = updatedAtRaw ? new Date(updatedAtRaw) : null;
  const archivedLabel =
    archivedDate && !Number.isNaN(archivedDate.getTime())
      ? archivedDate.toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
        })
      : null;

  const hasMetadata = isArchived
    ? hasSource || !!archivedLabel || !!reasonLabel || isResolved
    : (props.repoSlug ?? null) !== null ||
      hasSource ||
      !isReady ||
      report.actionability != null ||
      report.is_suggested_reviewer === true ||
      report.signal_count > 0;

  const body = (
    <>
      <PriorityMonogram priority={report.priority} />

      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="min-w-0">
          <InboxCardTitle
            tag={
              conventionalTitle && (
                <ConventionalCommitScopeTag
                  type={conventionalTitle.type}
                  scope={conventionalTitle.scope}
                  compact
                />
              )
            }
          >
            {cardTitle}
          </InboxCardTitle>
        </div>

        {isArchived ? (
          headline && (
            <span className="wrap-break-word line-clamp-2 min-w-0 text-[12.5px] text-gray-10 leading-snug">
              {headline}
            </span>
          )
        ) : (
          <div className={isReady ? "min-w-0" : "min-w-0 opacity-80"}>
            {headline ? (
              <span className="wrap-break-word line-clamp-2 text-[12.5px] text-gray-10 leading-snug">
                {headline}
              </span>
            ) : (
              <SignalReportSummaryMarkdown
                content={report.summary}
                fallback="No summary yet. Still collecting context."
                variant="list"
                pending={!isReady}
              />
            )}
          </div>
        )}

        {hasMetadata && (
          <div className="mt-1 flex min-w-0 flex-wrap items-center gap-2.5">
            <InboxCardSourceMeta
              repoSlug={isArchived ? null : (props.repoSlug ?? null)}
              sourceProducts={report.source_products}
              className=""
            />
            {isArchived ? (
              <>
                {archivedLabel && (
                  <span className="text-[12px] text-gray-10">
                    {isResolved ? "Resolved" : "Archived"} {archivedLabel}
                  </span>
                )}
                {isResolved ? (
                  <SignalReportStatusBadge status={report.status} />
                ) : (
                  reasonLabel && (
                    <span
                      className="max-w-full truncate rounded-(--radius-1) bg-(--gray-3) px-1.5 py-0.5 text-[11px] text-gray-11"
                      title={
                        dismissalNote
                          ? `${reasonLabel}: ${dismissalNote}`
                          : reasonLabel
                      }
                    >
                      {reasonLabel}
                    </span>
                  )
                )}
              </>
            ) : (
              <>
                {!isStatusRedundantWithActionability(
                  report.status,
                  report.actionability,
                ) && <SignalReportStatusBadge status={report.status} />}
                {report.actionability && (
                  <SignalReportActionabilityBadge
                    actionability={report.actionability}
                  />
                )}
                {report.is_suggested_reviewer && <ForYouBadge />}
                {report.signal_count > 0 && (
                  <span className="flex items-center gap-1 text-[12px] text-gray-10">
                    <LightningIcon size={11} />
                    <span className="tabular-nums">
                      {report.signal_count} signal
                      {report.signal_count !== 1 ? "s" : ""}
                    </span>
                  </span>
                )}
              </>
            )}
          </div>
        )}

        {!isArchived && (
          <InboxCardTimestamp
            timestamp={report.updated_at ?? report.created_at}
          />
        )}
      </div>
    </>
  );

  // A refunded/resolved archived report carries no actions; skip the rail (and
  // its divider) entirely rather than render an empty bordered column.
  const actions = isArchived ? (
    isResolved ? null : (
      <UiButton
        type="button"
        variant="soft"
        color="gray"
        size="1"
        aria-label="Restore this report to Self-driving"
        tooltipContent="Restore to Self-driving"
        loading={props.isRestorePending}
        disabled={props.isRestorePending}
        onClick={(event) => {
          event.stopPropagation();
          props.onRestore?.();
        }}
      >
        <ArrowCounterClockwiseIcon size={14} />
        Restore
      </UiButton>
    )
  ) : (
    <>
      <SuggestedReviewerAvatarStack
        report={report}
        artefacts={props.artefacts}
      />
      <UiButton
        type="button"
        variant="soft"
        color="gray"
        size="1"
        aria-label="Archive this report"
        tooltipContent="Archive this report"
        disabled={
          (props.dismissDisabledReason ?? null) !== null ||
          props.isDismissPending
        }
        disabledReason={props.dismissDisabledReason}
        loading={props.isDismissPending}
        onClick={(event) => {
          event.stopPropagation();
          props.onDismiss?.();
        }}
      >
        <ArchiveIcon size={14} />
      </UiButton>
      <Button
        type="button"
        variant="primary"
        size="sm"
        onClick={(event) => {
          event.stopPropagation();
          props.onReview?.();
        }}
      >
        Review
      </Button>
    </>
  );

  return (
    <div
      className={inboxCardClassName({
        dashed: true,
        isSelected: !isArchived && isSelected,
        dimmed: isArchived,
      })}
      {...rootProps}
    >
      {renderBody(body, inboxCardBodyClassName)}
      {actions && <InboxCardActions>{actions}</InboxCardActions>}
    </div>
  );
}

interface BaseReportCardProps {
  report: SignalReport;
  isSelected?: boolean;
  onRowClick?: (event: MouseEvent) => void;
}

interface DefaultReportCardProps extends BaseReportCardProps {
  variant?: "default";
  onDismiss: () => void;
  dismissDisabledReason?: string | null;
  isDismissPending?: boolean;
}

interface ArchivedReportCardProps extends BaseReportCardProps {
  variant: "archived";
  onRestore: () => void;
  isRestorePending?: boolean;
}

export type ReportCardProps = DefaultReportCardProps | ArchivedReportCardProps;

export function ReportCard(props: ReportCardProps) {
  const { report, isSelected = false, onRowClick } = props;
  const isArchived = props.variant === "archived";

  const detailRoute = isArchived
    ? {
        to: "/inbox/dismissed/$reportId" as const,
        params: { reportId: report.id },
      }
    : {
        to: "/inbox/reports/$reportId" as const,
        params: { reportId: report.id },
      };
  const { prefetch, pointerHandlers } = useInboxReportDetailPrefetch(
    report,
    detailRoute,
  );
  const navigate = useNavigate();
  // Archived rows are read-only, so skip the artefact fetch that powers the
  // repo slug + suggested-reviewer stack — neither is shown when archived.
  const { data: artefactsResp } = useInboxReportArtefacts(report.id, {
    enabled: !isArchived,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
  const repoSlug = isArchived
    ? null
    : extractRepoSelectionRepository(artefactsResp?.results);

  const renderBody = (body: ReactNode, className: string) => (
    <Link
      {...detailRoute}
      preload="intent"
      onClick={(event) => {
        onRowClick?.(event);
        if (event.metaKey || event.ctrlKey || event.shiftKey) {
          event.preventDefault();
          return;
        }
        prefetch();
      }}
      className={className}
    >
      {body}
    </Link>
  );

  if (props.variant === "archived") {
    return (
      <ReportCardView
        variant="archived"
        report={report}
        isSelected={isSelected}
        onRestore={props.onRestore}
        isRestorePending={props.isRestorePending}
        renderBody={renderBody}
        rootProps={pointerHandlers}
      />
    );
  }

  return (
    <ReportCardView
      report={report}
      isSelected={isSelected}
      repoSlug={repoSlug}
      artefacts={artefactsResp ?? null}
      onDismiss={props.onDismiss}
      dismissDisabledReason={props.dismissDisabledReason}
      isDismissPending={props.isDismissPending}
      onReview={() => {
        prefetch();
        navigate(detailRoute);
      }}
      renderBody={renderBody}
      rootProps={pointerHandlers}
    />
  );
}
