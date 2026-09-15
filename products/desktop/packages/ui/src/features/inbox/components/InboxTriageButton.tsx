import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { useTriageFocusEnabled } from "@posthog/ui/features/feature-flags/useTriageFocusEnabled";
import {
  INBOX_TRIAGE_ROUTE,
  isInboxTriagePath,
} from "@posthog/ui/features/inbox/triageRoute";
import { Link, useRouterState } from "@tanstack/react-router";
import type { ReactElement } from "react";

/**
 * Starts triage from the report list. Triage is a route, so this is a link.
 * An empty queue disables the button rather than hiding it: hidden, the list
 * reads as if triage had been taken away.
 */
export function InboxTriageButton({
  triageReportCount,
}: {
  triageReportCount: number;
}): ReactElement | null {
  const enabled = useTriageFocusEnabled();
  const inTriage = useRouterState({
    select: (state) => isInboxTriagePath(state.location.pathname),
  });
  if (!enabled || inTriage) return null;

  const canTriage = triageReportCount > 0;
  // Disabled it keeps its own element, which stays focusable and hoverable, so
  // the tooltip still says why the queue is closed.
  const button = canTriage ? (
    <Button
      variant="outline"
      size="sm"
      data-attr="inbox-triage-reports"
      nativeButton={false}
      render={<Link to={INBOX_TRIAGE_ROUTE} />}
    >
      Triage mode
    </Button>
  ) : (
    <Button
      variant="outline"
      size="sm"
      data-attr="inbox-triage-reports"
      disabled
    >
      Triage mode
    </Button>
  );

  return (
    <Tooltip>
      <TooltipTrigger render={button} />
      <TooltipContent side="bottom">
        {canTriage
          ? "Step through the reports that need a decision, one at a time. Press T to start."
          : "Nothing needs a decision right now."}
      </TooltipContent>
    </Tooltip>
  );
}
