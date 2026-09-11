import { XIcon } from "@phosphor-icons/react";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { useInboxTriageOrigin } from "@posthog/ui/features/inbox/hooks/useInboxBackTarget";
import {
  resolveNavigationSource,
  useReportSourceHref,
} from "@posthog/ui/router/reportNavigation";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import type { ReactElement } from "react";

/**
 * Puts the report down and leaves its list standing, the way Activity closes an
 * item. Drawn only when the report names where it was opened from: without a
 * source there is no list beside it and nothing to close back to.
 */
export function ReportDetailCloseButton(): ReactElement | null {
  const source = resolveNavigationSource(useReportSourceHref());
  // TanStack blanks history state on a plain navigate, so triage's place in
  // the queue has to travel with the click or the queue restarts at the top.
  const triageOrigin = useInboxTriageOrigin();
  if (!source) return null;

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            className="no-drag shrink-0"
            aria-label="Close report"
            data-attr="report-detail-close"
            onClick={() =>
              void getRouterOrNull()?.navigate({
                href: source.href,
                state: (previous) => ({
                  ...previous,
                  ...(triageOrigin ? { inboxTriageOrigin: triageOrigin } : {}),
                }),
              })
            }
          />
        }
      >
        <XIcon size={14} />
      </TooltipTrigger>
      <TooltipContent side="bottom">Close report</TooltipContent>
    </Tooltip>
  );
}
