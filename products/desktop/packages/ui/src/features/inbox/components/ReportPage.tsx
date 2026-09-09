import { isDismissedReport } from "@posthog/core/inbox/reportMembership";
import type { SignalReport } from "@posthog/shared/types";
import { DismissedReportDetailContent } from "@posthog/ui/features/inbox/components/DismissedReportDetail";
import {
  InboxReportDetailGate,
  ReportOpenTracker,
} from "@posthog/ui/features/inbox/components/InboxReportDetailGate";
import { PullRequestDetailContent } from "@posthog/ui/features/inbox/components/PullRequestDetail";
import { ReportDetailContent } from "@posthog/ui/features/inbox/components/ReportDetail";
import { ReportPageContext } from "@posthog/ui/features/inbox/components/ReportPageContext";
import { SettingsLayout } from "@posthog/ui/features/settings/components/SettingsLayout";
import {
  resolveNavigationSource,
  useReportSourceHref,
} from "@posthog/ui/router/reportNavigation";

export function ReportPage({
  reportId,
  cachedReport,
}: {
  reportId: string;
  cachedReport: SignalReport | null;
}) {
  const source = resolveNavigationSource(useReportSourceHref());
  const content = (
    <div className="h-full min-h-0 w-full overflow-auto">
      <InboxReportDetailGate
        reportId={reportId}
        cachedReport={cachedReport}
        backTo="/"
        backLinkTo={source?.href ?? "/inbox/reports"}
        backLabel={source?.label ?? "Self-driving"}
        statusRedirect={false}
        requireFreshStatus
        missingCopy="This report couldn't be found or you don't have access to it."
      >
        {(report) => <ReportPageContent report={report} />}
      </InboxReportDetailGate>
    </div>
  );
  return source?.settingsCategory ? (
    <SettingsLayout category={source.settingsCategory}>
      {content}
    </SettingsLayout>
  ) : (
    content
  );
}

function ReportPageContent({ report }: { report: SignalReport }) {
  const archived = isDismissedReport(report);
  const hasPr = Boolean(report.implementation_pr_url);
  return (
    <ReportPageContext value={report}>
      {!archived && (
        <ReportOpenTracker report={report} tab={hasPr ? "pulls" : "reports"} />
      )}
      {archived ? (
        <DismissedReportDetailContent
          report={report}
          back={{ to: "/inbox/dismissed", label: "Report" }}
        />
      ) : hasPr ? (
        <PullRequestDetailContent report={report} />
      ) : (
        <ReportDetailContent report={report} backTo="/" backLabel="Report" />
      )}
    </ReportPageContext>
  );
}
