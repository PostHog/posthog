import {
  ArchiveIcon,
  FileTextIcon,
  GitPullRequestIcon,
  SpinnerGapIcon,
} from "@phosphor-icons/react";
import {
  INBOX_DISMISSED_STATUS_FILTER,
  INBOX_PIPELINE_STATUS_FILTER,
  INBOX_REFETCH_INTERVAL_MS,
} from "@posthog/core/inbox/reportFiltering";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
} from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { ReportSessionCard } from "@posthog/ui/features/canvas/reports/ReportSessionCard";
import {
  partitionReportSessions,
  type ReportSessionSection,
} from "@posthog/ui/features/canvas/reports/reportSessions";
import { useInboxReportsInfinite } from "@posthog/ui/features/inbox/hooks/useInboxReports";

const SECTION_META: Record<
  ReportSessionSection,
  { title: string; Icon: typeof FileTextIcon }
> = {
  reports: { title: "Reports", Icon: FileTextIcon },
  runs: { title: "Running work", Icon: SpinnerGapIcon },
  pulls: { title: "Pull requests", Icon: GitPullRequestIcon },
  archive: { title: "Archive", Icon: ArchiveIcon },
};

export function ReportSessions({ channelId }: { channelId: string }) {
  const active = useInboxReportsInfinite(
    { status: INBOX_PIPELINE_STATUS_FILTER, ordering: "-updated_at" },
    { refetchInterval: INBOX_REFETCH_INTERVAL_MS },
  );
  const archived = useInboxReportsInfinite(
    { status: INBOX_DISMISSED_STATUS_FILTER, ordering: "-updated_at" },
    { refetchInterval: INBOX_REFETCH_INTERVAL_MS },
  );
  const sections = partitionReportSessions([
    ...active.allReports,
    ...archived.allReports,
  ]);
  return (
    <ReportSessionsView
      channelId={channelId}
      sections={sections}
      loading={active.isLoading || archived.isLoading}
      error={active.isError || archived.isError}
    />
  );
}

export function ReportSessionsView({
  channelId,
  sections,
  loading = false,
  error = false,
}: {
  channelId: string;
  sections: Record<ReportSessionSection, SignalReport[]>;
  loading?: boolean;
  error?: boolean;
}) {
  const hasReports = Object.values(sections).some(
    (reports) => reports.length > 0,
  );

  if (loading && !hasReports) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  if (error && !hasReports) {
    return (
      <Empty className="flex-1">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileTextIcon />
          </EmptyMedia>
          <EmptyTitle>Couldn't load reports</EmptyTitle>
          <EmptyDescription>Refresh the page to try again.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  if (!hasReports) {
    return (
      <Empty className="flex-1">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileTextIcon />
          </EmptyMedia>
          <EmptyTitle>No reports yet</EmptyTitle>
          <EmptyDescription>
            Reports from PostHog will appear here as sessions.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-6 py-8">
      {(["reports", "runs", "pulls", "archive"] as const).map((key) => {
        const reports = sections[key];
        if (reports.length === 0) return null;
        const { title, Icon } = SECTION_META[key];
        return (
          <section key={key}>
            <div className="mb-3 flex items-center gap-2">
              <Icon size={15} className="text-muted" />
              <h2 className="font-semibold text-sm">{title}</h2>
              <span className="text-muted text-xs">{reports.length}</span>
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
              {reports.map((report) => (
                <ReportSessionCard
                  key={report.id}
                  channelId={channelId}
                  report={report}
                  archived={key === "archive"}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
