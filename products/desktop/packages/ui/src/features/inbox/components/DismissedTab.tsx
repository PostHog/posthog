import { ArchiveIcon } from "@phosphor-icons/react";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { CardSkeleton } from "@posthog/ui/features/inbox/components/CardSkeleton";
import { InboxLoadMore } from "@posthog/ui/features/inbox/components/InboxLoadMore";
import { ReportCard } from "@posthog/ui/features/inbox/components/ReportCard";
import { useInboxDismissedReports } from "@posthog/ui/features/inbox/hooks/useInboxDismissedReports";
import { useInboxRestoreReport } from "@posthog/ui/features/inbox/hooks/useInboxRestoreReport";
import { Flex } from "@radix-ui/themes";

/**
 * Archive tab: terminal reports, newest first — ones the user archived
 * (suppressed, restorable back into the pipeline) and ones resolved by a merged
 * implementation PR (shown for reference only, not restorable). Each card opens
 * a read-only detail view (summary + evidence) — no triage affordances.
 */
export function DismissedTab() {
  const { reports, isLoading, hasNextPage, isFetchingNextPage, fetchNextPage } =
    useInboxDismissedReports();
  const restore = useInboxRestoreReport();
  const restoringId = restore.isPending ? restore.variables : null;

  if (isLoading && reports.length === 0) {
    return (
      <Flex direction="column" gap="4" className="mx-auto max-w-4xl px-6 py-4">
        <CardSkeleton count={4} variant="cards" />
      </Flex>
    );
  }

  if (reports.length === 0) {
    return (
      <Flex direction="column" className="mx-auto max-w-4xl px-6 py-4">
        <Empty className="mx-auto max-w-md py-16">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <ArchiveIcon size={24} />
            </EmptyMedia>
            <EmptyTitle>No archived reports</EmptyTitle>
            <EmptyDescription>
              Reports you archive from your inbox show up here, and you can
              restore any of them. Resolved reports (their pull request merged)
              also appear here for reference.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      </Flex>
    );
  }

  return (
    <Flex direction="column" gap="3" className="mx-auto max-w-4xl px-6 py-4">
      {reports.map((report) => (
        <ReportCard
          key={report.id}
          variant="archived"
          report={report}
          onRestore={() => restore.mutate(report.id)}
          isRestorePending={restoringId === report.id}
        />
      ))}
      <InboxLoadMore
        hasNextPage={hasNextPage}
        isFetchingNextPage={isFetchingNextPage}
        onLoadMore={() => void fetchNextPage({ cancelRefetch: false })}
      />
    </Flex>
  );
}
