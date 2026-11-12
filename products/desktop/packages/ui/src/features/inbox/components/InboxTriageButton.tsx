import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import {
  INBOX_TRIAGE_ROUTE,
  isInboxTriagePath,
} from "@posthog/ui/features/inbox/triageRoute";
import { Link, useRouterState } from "@tanstack/react-router";
import type { ReactElement } from "react";

/** Starts triage from the report list. Triage is a route, so this is a link. */
export function InboxTriageButton({
  triageReportCount,
}: {
  triageReportCount: number;
}): ReactElement | null {
  const inTriage = useRouterState({
    select: (state) => isInboxTriagePath(state.location.pathname),
  });
  if (inTriage || triageReportCount === 0) return null;

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="outline"
            size="sm"
            data-attr="inbox-triage-reports"
            render={<Link to={INBOX_TRIAGE_ROUTE} />}
          >
            Triage mode
          </Button>
        }
      />
      <TooltipContent side="bottom">Press T to start triage</TooltipContent>
    </Tooltip>
  );
}
