import type { ScoutRun } from "@posthog/api-client/posthog-client";
import { deriveHeadline } from "@posthog/core/inbox/reportPresentation";
import { scoutRunReports } from "@posthog/core/scouts/scoutPresentation";
import { Badge, Button, Skeleton } from "@posthog/quill";
import { useInboxReportById } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useOpenInboxReport } from "@posthog/ui/features/inbox/hooks/useOpenInboxReport";
import { useInView } from "framer-motion";
import { useRef, useState } from "react";

export function ScoutRunReportLinks({ run }: { run: ScoutRun }) {
  const reports = scoutRunReports(run);
  if (reports.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {reports.map((report) => (
        <ScoutReportLink
          key={report.id}
          reportId={report.id}
          action={report.action}
        />
      ))}
    </div>
  );
}

function ScoutReportLink({
  reportId,
  action,
}: {
  reportId: string;
  action: "created" | "updated";
}) {
  const ref = useRef<HTMLDivElement>(null);
  const visible = useInView(ref, { once: true, margin: "200px" });
  const {
    data: report,
    isLoading,
    isError,
    refetch,
  } = useInboxReportById(reportId, { enabled: visible });
  const openReport = useOpenInboxReport();
  const [opening, setOpening] = useState(false);
  const headline = deriveHeadline(report?.summary);

  return (
    <div
      ref={ref}
      className="rounded-(--radius-md) border border-border bg-(--color-panel-solid)"
    >
      <button
        type="button"
        data-attr="scout-report-link"
        disabled={opening}
        onClick={async () => {
          setOpening(true);
          try {
            await openReport(reportId);
          } finally {
            setOpening(false);
          }
        }}
        className="flex w-full items-start gap-3 rounded-(--radius-md) px-3 py-3 text-left hover:bg-(--gray-3) focus-visible:outline focus-visible:outline-(--gray-8) focus-visible:outline-2 disabled:opacity-60"
      >
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          {isLoading || (!visible && !report) ? (
            <Skeleton className="h-4 w-64 max-w-full" />
          ) : (
            <span className="break-words font-medium text-[13px] text-gray-12">
              {report?.title ||
                (isError
                  ? "Could not load report"
                  : report
                    ? "Untitled report"
                    : "Report unavailable")}
            </span>
          )}
          {headline ? (
            <span className="line-clamp-2 break-words text-[12px] text-gray-11">
              {headline}
            </span>
          ) : null}
          {!report ? (
            <span className="text-[11px] text-gray-10">
              Report {reportId.slice(0, 8)}
            </span>
          ) : null}
        </span>
        <Badge variant="default">
          {action === "created" ? "Created" : "Updated"}
        </Badge>
        {report?.priority ? (
          <Badge variant="default">{report.priority}</Badge>
        ) : null}
      </button>
      {isError ? (
        <Button variant="link-muted" size="sm" onClick={() => void refetch()}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}
