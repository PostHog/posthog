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
  const inbox = useInboxSectionedReports({ autoPage: true });
  const triageOrigin = useInboxTriageOrigin();
  const hasActiveFilters = useInboxSignalsFilterStore(
    hasActiveReportsListFilters,
  );
  const navigate = useNavigate();

  // The queue is filtered by task state, so a loaded page can hold no decision
  // while a later page still does. Handing that page to triage would end the
  // session and record a triage that was never done. Task state is waited on
  // the same way, because Create PR reloads it: blanking a queue that is on
  // screen unmounts triage and loses the place the reader had in it.
  if (
    inbox.isLoading ||
    (inbox.triageReports.length === 0 &&
      (inbox.triageLoading || inbox.triagePagePending))
  ) {
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
