import {
  ArrowLeftIcon,
  FileTextIcon,
  MagnifyingGlassIcon,
} from "@phosphor-icons/react";
import {
  Button,
  Card,
  CardContent,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
} from "@posthog/quill";
import { ReportActivitySection } from "@posthog/ui/features/inbox/components/detail/ReportActivitySection";
import { ReportFeedbackFooter } from "@posthog/ui/features/inbox/components/detail/ReportFeedbackFooter";
import { ReportDetailActions } from "@posthog/ui/features/inbox/components/ReportDetailActions";
import { ReportTasksSection } from "@posthog/ui/features/inbox/components/ReportTasksSection";
import {
  SignalsList,
  SignalsListSkeleton,
} from "@posthog/ui/features/inbox/components/SignalsList";
import { SuggestedReviewersSection } from "@posthog/ui/features/inbox/components/SuggestedReviewersSection";
import { SignalReportActionabilityBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportActionabilityBadge";
import { SignalReportPriorityBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportPriorityBadge";
import { SignalReportStatusBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportStatusBadge";
import { SignalReportSummaryMarkdown } from "@posthog/ui/features/inbox/components/utils/SignalReportSummaryMarkdown";
import {
  useInboxReportById,
  useInboxReportSignals,
} from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { Link } from "@tanstack/react-router";

export function ReportCanvas({
  channelId,
  reportId,
}: {
  channelId: string;
  reportId: string;
}) {
  const reportQuery = useInboxReportById(reportId);
  const signalsQuery = useInboxReportSignals(reportId);
  const report = reportQuery.data;

  if (reportQuery.isLoading && !report) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (!report) {
    return (
      <Empty className="h-full">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileTextIcon />
          </EmptyMedia>
          <EmptyTitle>Report not found</EmptyTitle>
          <EmptyDescription>
            This report may have been removed.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  const signals = signalsQuery.data?.signals ?? [];
  const evidenceCount = signalsQuery.data
    ? signals.length
    : report.signal_count;
  const archived =
    report.status === "suppressed" || report.status === "resolved";
  return (
    <div className="h-full overflow-y-auto bg-surface-primary">
      <div className="mx-auto w-full max-w-6xl px-6 py-6">
        <Button
          variant="link-muted"
          size="sm"
          render={<Link to="/website/$channelId" params={{ channelId }} />}
        >
          <ArrowLeftIcon size={14} /> Back to space
        </Button>
        <div className="mt-5 flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              {report.priority && (
                <SignalReportPriorityBadge priority={report.priority} />
              )}
              <SignalReportStatusBadge status={report.status} />
              {report.actionability && (
                <SignalReportActionabilityBadge
                  actionability={report.actionability}
                />
              )}
            </div>
            <h1 className="font-semibold text-2xl">
              {report.title || "Untitled report"}
            </h1>
          </div>
          {!archived && (
            <div className="flex items-center gap-2">
              <ReportDetailActions report={report} />
            </div>
          )}
        </div>
        <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
          <Card>
            <CardContent className="p-5">
              <div className="mb-3 flex items-center gap-2">
                <FileTextIcon size={16} />
                <h2 className="font-semibold">Summary</h2>
              </div>
              <SignalReportSummaryMarkdown
                content={report.summary}
                fallback="No summary yet. The agent is still investigating."
                variant="detail"
                pending={report.status === "in_progress"}
              />
            </CardContent>
          </Card>
          <div className="flex flex-col gap-5">
            {evidenceCount > 0 && (
              <Card>
                <CardContent className="p-5">
                  <div className="mb-3 flex items-center gap-2">
                    <MagnifyingGlassIcon size={16} />
                    <h2 className="font-semibold">Evidence</h2>
                    <span className="ml-auto text-muted text-xs">
                      {evidenceCount}
                    </span>
                  </div>
                  {signalsQuery.data ? (
                    <SignalsList signals={signals} />
                  ) : (
                    <SignalsListSkeleton count={evidenceCount} />
                  )}
                </CardContent>
              </Card>
            )}
            <ReportTasksSection report={report} />
            {!archived && <SuggestedReviewersSection report={report} />}
            <ReportActivitySection reportId={report.id} />
          </div>
        </div>
        {!archived && (
          <div className="mt-5">
            <ReportFeedbackFooter report={report} />
          </div>
        )}
      </div>
    </div>
  );
}
