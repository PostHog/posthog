import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { ReportTriageFocus } from "@posthog/ui/features/inbox/components/ReportTriageFocus";
import { useInboxTriageOrigin } from "@posthog/ui/features/inbox/hooks/useInboxBackTarget";
import { useInboxSectionedReports } from "@posthog/ui/features/inbox/hooks/useInboxSectionedReports";
import {
  hasActiveReportsListFilters,
  useInboxSignalsFilterStore,
} from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { useNavigate } from "@tanstack/react-router";
import type { ReactElement } from "react";

export function InboxTriagePane(): ReactElement {
  // Beside the rail the sidebar list owns paging; without it, nothing else is
  // reading this list, so triage walks the pages itself.
  const spacesLayout = useChannelsLayout();
  const inbox = useInboxSectionedReports({ autoPage: !spacesLayout });
  const triageOrigin = useInboxTriageOrigin();
  const hasActiveFilters = useInboxSignalsFilterStore(
    hasActiveReportsListFilters,
  );
  const navigate = useNavigate();

  if (inbox.isLoading) {
    return <LoadingState className="h-full" />;
  }

  return (
    <div className="h-full min-h-0">
      <ReportTriageFocus
        reports={inbox.triageReports}
        allReports={inbox.reports}
        scope={inbox.scope}
        hasActiveFilters={hasActiveFilters}
        initialReportId={triageOrigin?.reportId}
        onExit={() => void navigate({ to: "/inbox", replace: true })}
      />
    </div>
  );
}
