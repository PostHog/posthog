import { EnvelopeSimpleIcon, SparkleIcon } from "@phosphor-icons/react";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Kbd,
} from "@posthog/quill";
import { useTriageFocusEnabled } from "@posthog/ui/features/feature-flags/useTriageFocusEnabled";
import { useInboxSectionedReports } from "@posthog/ui/features/inbox/hooks/useInboxSectionedReports";
import { useInboxTriageHotkey } from "@posthog/ui/features/inbox/hooks/useInboxTriageHotkey";
import { useSelfDrivingSetupStatus } from "@posthog/ui/features/inbox/hooks/useSelfDrivingSetupStatus";
import {
  hasActiveReportsListFilters,
  useInboxSignalsFilterStore,
} from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { INBOX_TRIAGE_ROUTE } from "@posthog/ui/features/inbox/triageRoute";
import { OpenSidebarButton } from "@posthog/ui/features/sidebar/components/OpenSidebarButton";
import { navigateToSettings } from "@posthog/ui/router/navigationBridge";
import { Link } from "@tanstack/react-router";
import type { ReactElement } from "react";

/**
 * What Self-driving shows beside its list until a report is picked. Paging is
 * the sidebar list's job, so this reads the same reports without driving it.
 */
export function InboxHomePane(): ReactElement {
  const inbox = useInboxSectionedReports({ autoPage: false });
  const triageEnabled = useTriageFocusEnabled();
  const setupStatus = useSelfDrivingSetupStatus();
  const hasActiveFilters = useInboxSignalsFilterStore(
    hasActiveReportsListFilters,
  );

  useInboxTriageHotkey({
    enabled: triageEnabled,
    triageReportCount: inbox.triageReports.length,
  });

  const needsSetup =
    inbox.isEmpty &&
    !hasActiveFilters &&
    !setupStatus.isLoading &&
    !setupStatus.isConfigured;
  const canTriage = triageEnabled && inbox.triageReports.length > 0;

  return (
    <div className="flex h-full items-center justify-center">
      <Empty className="max-w-md border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            {needsSetup ? <SparkleIcon /> : <EnvelopeSimpleIcon />}
          </EmptyMedia>
          <EmptyTitle>
            {needsSetup ? "Ship fixes while you sleep" : "Nothing selected"}
          </EmptyTitle>
          <EmptyDescription>
            {needsSetup
              ? "PostHog watches your session replays, errors, and Slack, then opens a pull request when it finds something worth fixing. Connect a source to get started."
              : "Pick a report from the list to read it here."}
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          {needsSetup ? (
            <Button
              variant="primary"
              size="default"
              onClick={() => navigateToSettings("agents")}
            >
              Configure agents
            </Button>
          ) : (
            <>
              <OpenSidebarButton />
              {canTriage && (
                <Button
                  variant="outline"
                  size="default"
                  render={<Link to={INBOX_TRIAGE_ROUTE} />}
                >
                  Triage mode
                  <Kbd>T</Kbd>
                </Button>
              )}
            </>
          )}
        </EmptyContent>
      </Empty>
    </div>
  );
}
