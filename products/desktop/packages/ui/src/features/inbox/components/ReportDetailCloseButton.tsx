import { XIcon } from "@phosphor-icons/react";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { useCloseReport } from "@posthog/ui/features/inbox/hooks/useCloseReport";
import type { ReactElement } from "react";

/**
 * Puts the report down and leaves its list standing, the way Activity closes an
 * item. Drawn only when the report names where it was opened from: without a
 * source there is no list beside it and nothing to close back to.
 */
export function ReportDetailCloseButton(): ReactElement | null {
  const closeReport = useCloseReport();
  if (!closeReport) return null;

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
            onClick={closeReport}
          />
        }
      >
        <XIcon size={14} />
      </TooltipTrigger>
      <TooltipContent side="bottom">Close report</TooltipContent>
    </Tooltip>
  );
}
