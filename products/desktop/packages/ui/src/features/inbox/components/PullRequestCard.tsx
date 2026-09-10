import { ArchiveIcon } from "@phosphor-icons/react";
import { extractRepoSelectionRepository } from "@posthog/core/inbox/artefacts";
import {
  deriveHeadline,
  displayConventionalCommitTitle,
  parseConventionalCommitTitle,
  parsePrUrl,
} from "@posthog/core/inbox/reportPresentation";
import { Button, cn } from "@posthog/quill";
import type {
  SignalReport,
  SignalReportArtefactsResponse,
} from "@posthog/shared/types";
import { ConventionalCommitScopeTag } from "@posthog/ui/features/inbox/components/ConventionalCommitScopeTag";
import {
  InboxCardActions,
  InboxCardSelectionCheckbox,
  InboxCardTimestamp,
  InboxCardTopRight,
  inboxCardBodyClassName,
  inboxCardClassName,
} from "@posthog/ui/features/inbox/components/InboxCardChrome";
import { InboxCardSourceMeta } from "@posthog/ui/features/inbox/components/InboxCardSourceMeta";
import { InboxCardTitle } from "@posthog/ui/features/inbox/components/InboxCardTitle";
import { PrDiffStats } from "@posthog/ui/features/inbox/components/PrDiffStats";
import { PriorityMonogram } from "@posthog/ui/features/inbox/components/PriorityMonogram";
import { SuggestedReviewerAvatarStack } from "@posthog/ui/features/inbox/components/SuggestedReviewerAvatarStack";
import { ReportImplementationPrLink } from "@posthog/ui/features/inbox/components/utils/ReportImplementationPrLink";
import { useInboxReportCardSelection } from "@posthog/ui/features/inbox/hooks/useInboxReportCardSelection";
import { useInboxReportDetailPrefetch } from "@posthog/ui/features/inbox/hooks/useInboxReportDetailPrefetch";
import { useInboxReportArtefacts } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { Button as UiButton } from "@posthog/ui/primitives/Button";
import {
  navigationSourceHref,
  reportNavigationState,
} from "@posthog/ui/router/reportNavigation";
import { Link, useNavigate } from "@tanstack/react-router";
import type { HTMLAttributes, ReactNode } from "react";

export interface PullRequestCardViewProps {
  report: SignalReport;
  repoSlug?: string | null;
  /** Resolved artefacts for the reviewer stack; null renders no avatars. */
  artefacts: SignalReportArtefactsResponse | null;
  isSelected?: boolean;
  onDismiss?: () => void;
  dismissDisabledReason?: string | null;
  isDismissPending?: boolean;
  onReview?: () => void;
  /** Wraps the card body; the container passes the detail-route Link. */
  renderBody: (body: ReactNode, className: string) => ReactNode;
  rootProps?: HTMLAttributes<HTMLDivElement>;
}

/** Pure card; the container wires routing, prefetch, and artefact data. */
export function PullRequestCardView({
  report,
  repoSlug,
  artefacts,
  isSelected = false,
  onDismiss,
  dismissDisabledReason = null,
  isDismissPending = false,
  onReview,
  renderBody,
  rootProps,
}: PullRequestCardViewProps) {
  const conventionalTitle = parseConventionalCommitTitle(report.title);
  const cardTitle = displayConventionalCommitTitle(
    report.title,
    "Untitled pull request",
  );
  const headline = deriveHeadline(report.summary);

  const body = (
    <>
      <PriorityMonogram priority={report.priority} />

      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        {/* Pad clear of the absolute PR pill while the title spans the full card width. */}
        <div className="min-w-0 @lg:pr-0 pr-16">
          <InboxCardTitle
            tag={
              conventionalTitle && (
                <ConventionalCommitScopeTag
                  type={conventionalTitle.type}
                  scope={conventionalTitle.scope}
                />
              )
            }
          >
            {cardTitle}
          </InboxCardTitle>
        </div>

        {headline && (
          <span className="wrap-break-word line-clamp-2 min-w-0 text-[12.5px] text-gray-10 leading-snug">
            {headline}
          </span>
        )}

        <div className="flex min-w-0 flex-wrap items-center gap-2.5">
          <InboxCardSourceMeta
            repoSlug={repoSlug}
            sourceProducts={report.source_products}
            className=""
          />
          {report.implementation_pr_url && (
            <PrDiffStats
              prUrl={report.implementation_pr_url}
              hideWhileLoading
            />
          )}
        </div>

        <InboxCardTimestamp
          timestamp={report.updated_at ?? report.created_at}
        />
      </div>
    </>
  );

  return (
    <div className={inboxCardClassName({ isSelected })} {...rootProps}>
      {report.implementation_pr_url && (
        <InboxCardTopRight>
          <ReportImplementationPrLink
            prUrl={report.implementation_pr_url}
            size="sm"
          />
        </InboxCardTopRight>
      )}

      {renderBody(body, inboxCardBodyClassName)}

      <InboxCardActions>
        <SuggestedReviewerAvatarStack report={report} artefacts={artefacts} />
        <UiButton
          type="button"
          variant="soft"
          color="gray"
          size="1"
          aria-label="Archive this report"
          tooltipContent="Archive this report"
          disabled={dismissDisabledReason !== null || isDismissPending}
          disabledReason={dismissDisabledReason}
          loading={isDismissPending}
          onClick={(event) => {
            event.stopPropagation();
            onDismiss?.();
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
            onReview?.();
          }}
        >
          Review
        </Button>
      </InboxCardActions>
    </div>
  );
}

interface PullRequestCardProps {
  report: SignalReport;
  onDismiss: () => void;
  dismissDisabledReason?: string | null;
  isDismissPending?: boolean;
}

export function PullRequestCard({
  report,
  onDismiss,
  dismissDisabledReason = null,
  isDismissPending = false,
}: PullRequestCardProps) {
  const source = navigationSourceHref();
  const detailRoute = {
    to: "/reports/$reportId" as const,
    params: { reportId: report.id },
    search: source ? { from: source } : {},
  };
  const { prefetch, pointerHandlers } =
    useInboxReportDetailPrefetch(detailRoute);
  const selection = useInboxReportCardSelection(report.id, true);
  const navigate = useNavigate();
  const prRef = report.implementation_pr_url
    ? parsePrUrl(report.implementation_pr_url)
    : null;
  const { data: artefactsResp } = useInboxReportArtefacts(report.id, {
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
  const repoSlug =
    extractRepoSelectionRepository(artefactsResp?.results) ?? prRef?.repoSlug;

  return (
    <PullRequestCardView
      report={report}
      repoSlug={repoSlug}
      artefacts={artefactsResp ?? null}
      isSelected={selection.isSelected}
      onDismiss={onDismiss}
      dismissDisabledReason={dismissDisabledReason}
      isDismissPending={isDismissPending}
      onReview={() => {
        prefetch();
        navigate(detailRoute);
      }}
      rootProps={pointerHandlers}
      renderBody={(body, className) => (
        <div className="flex min-w-0 flex-1 items-start">
          <InboxCardSelectionCheckbox
            checked={selection.isSelected}
            selectionMode={selection.selectionMode}
            label={`Select pull request: ${report.title}`}
            onToggle={() => selection.toggle("checkbox")}
          />
          {/* The gestures sit on this wrapper, not on the link: a selecting click has to be
              caught before the link acts on it. */}
          <div
            className={cn(
              "flex min-w-0 flex-1",
              // A long press must not paint the title as selected text under the pointer.
              selection.isHolding && "select-none",
            )}
            {...selection.cardHandlers}
          >
            <Link
              {...detailRoute}
              state={reportNavigationState}
              preload="intent"
              onClick={(event) => {
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
          </div>
        </div>
      )}
    />
  );
}
