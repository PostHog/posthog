import {
  REPORT_IMPLEMENTATION_LABELS,
  type ReportImplementationState,
  type ReportImplementationTone,
  reportImplementationTone,
} from "@posthog/core/inbox/reportImplementation";
import { cn } from "@posthog/quill";

const TONE_CLASS: Record<ReportImplementationTone, string> = {
  progress: "text-blue-11",
  neutral: "text-muted-foreground",
  attention: "text-amber-11",
};

/**
 * A report row's implementation line. A settled verdict reads neutral so it is
 * not mistaken for a run that stalled or failed.
 */
export function ReportImplementationStatus({
  state,
  className,
}: {
  state: ReportImplementationState;
  className?: string;
}): React.JSX.Element {
  return (
    <span
      className={cn(
        "flex items-center gap-1.5 text-[12px]",
        TONE_CLASS[reportImplementationTone(state)],
        className,
      )}
    >
      <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
      {REPORT_IMPLEMENTATION_LABELS[state]}
    </span>
  );
}
