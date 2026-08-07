import { ArchiveIcon } from "@phosphor-icons/react";
import { extractRepoSelectionRepository } from "@posthog/core/inbox/artefacts";
import {
  deriveHeadline,
  displayConventionalCommitTitle,
  parseConventionalCommitTitle,
  parsePrUrl,
} from "@posthog/core/inbox/reportPresentation";
import { Button, cn } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { ConventionalCommitScopeTag } from "@posthog/ui/features/inbox/components/ConventionalCommitScopeTag";
import { InboxCardSourceMeta } from "@posthog/ui/features/inbox/components/InboxCardSourceMeta";
import { InboxCardTitle } from "@posthog/ui/features/inbox/components/InboxCardTitle";
import { PrDiffStats } from "@posthog/ui/features/inbox/components/PrDiffStats";
import { PriorityMonogram } from "@posthog/ui/features/inbox/components/PriorityMonogram";
import { SuggestedReviewerAvatarStack } from "@posthog/ui/features/inbox/components/SuggestedReviewerAvatarStack";
import { ReportImplementationPrLink } from "@posthog/ui/features/inbox/components/utils/ReportImplementationPrLink";
import { useInboxReportDetailPrefetch } from "@posthog/ui/features/inbox/hooks/useInboxReportDetailPrefetch";
import { useInboxReportArtefacts } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { Button as UiButton } from "@posthog/ui/primitives/Button";
import { Flex, Text } from "@radix-ui/themes";
import { Link, useNavigate } from "@tanstack/react-router";
import type { MouseEvent } from "react";

interface PullRequestCardProps {
  report: SignalReport;
  isSelected?: boolean;
  onRowClick?: (event: MouseEvent) => void;
  onDismiss: () => void;
  dismissDisabledReason?: string | null;
  isDismissPending?: boolean;
}

export function PullRequestCard({
  report,
  isSelected = false,
  onRowClick,
  onDismiss,
  dismissDisabledReason = null,
  isDismissPending = false,
}: PullRequestCardProps) {
  const detailRoute = {
    to: "/code/inbox/pulls/$reportId" as const,
    params: { reportId: report.id },
  };
  const { prefetch, pointerHandlers } = useInboxReportDetailPrefetch(
    report,
    detailRoute,
  );
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

  const conventionalTitle = parseConventionalCommitTitle(report.title);
  const cardTitle = displayConventionalCommitTitle(
    report.title,
    "Untitled pull request",
  );

  return (
    <div
      className={cn(
        "group flex w-full items-start gap-3 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-4 py-3.5 transition duration-150 hover:border-(--gray-6) hover:bg-(--gray-2) hover:shadow-sm",
        isSelected &&
          "border-(--accent-8) bg-(--accent-2) ring-(--accent-8) ring-2 ring-inset",
      )}
      {...pointerHandlers}
    >
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
        className="flex min-w-0 flex-1 items-start gap-3 text-left text-inherit no-underline focus-visible:outline-none"
      >
        <PriorityMonogram priority={report.priority} />

        <Flex direction="column" gap="1.5" className="min-w-0 flex-1">
          <Flex align="center" gap="1" wrap="wrap" className="min-w-0">
            {conventionalTitle && (
              <ConventionalCommitScopeTag
                type={conventionalTitle.type}
                scope={conventionalTitle.scope}
                compact
              />
            )}
            <InboxCardTitle>{cardTitle}</InboxCardTitle>
          </Flex>

          {(() => {
            const headline = deriveHeadline(report.summary);
            return headline ? (
              <Text className="wrap-break-word mt-0.5 line-clamp-2 text-[12.5px] text-gray-10 leading-snug">
                {headline}
              </Text>
            ) : null;
          })()}

          <InboxCardSourceMeta
            repoSlug={repoSlug}
            sourceProducts={report.source_products}
          />
        </Flex>
      </Link>

      <Flex
        align="center"
        className="gap-3.5 self-stretch border-border border-l pl-3"
      >
        <Flex align="center" gap="2" className="shrink-0">
          {report.implementation_pr_url && (
            <Flex direction="column" align="end" gap="1" className="shrink-0">
              <ReportImplementationPrLink
                prUrl={report.implementation_pr_url}
                size="sm"
              />
              <PrDiffStats
                prUrl={report.implementation_pr_url}
                hideWhileLoading
              />
            </Flex>
          )}
          <SuggestedReviewerAvatarStack
            reportId={report.id}
            artefacts={artefactsResp ?? null}
          />
        </Flex>
        <Flex align="center" className="shrink-0 gap-2.5">
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
              onDismiss();
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
              prefetch();
              navigate(detailRoute);
            }}
          >
            Review
          </Button>
        </Flex>
      </Flex>
    </div>
  );
}
