import {
  ThreadItemTimestamp,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";

function ordinal(value: number): string {
  const remainder = value % 100;
  const suffixes = ["th", "st", "nd", "rd"];
  return `${value}${suffixes[(remainder - 20) % 10] ?? suffixes[remainder] ?? suffixes[0]}`;
}

function formatClock(date: Date): string {
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const meridiem = date.getHours() >= 12 ? "pm" : "am";
  const hour = date.getHours() % 12 || 12;
  return `${hour}:${minutes}${meridiem}`;
}

function formatTooltip(date: Date): string {
  const month = date.toLocaleString("en-US", { month: "long" });
  return `${month} ${ordinal(date.getDate())} at ${formatClock(date)}`;
}

// Sits next to the actor rather than out at the row's right edge, a step below the
// 13px row copy. Sized here rather than by an ancestor
// `[data-slot=thread-item-timestamp]` rule: `TooltipTrigger` replaces the wrapped
// element's `data-slot` with its own, so such a rule never matches.
export function ThreadTimestamp({ dateTime }: { dateTime: string }) {
  const date = new Date(dateTime);
  if (Number.isNaN(date.getTime())) return null;

  return (
    <TooltipProvider delay={300}>
      <Tooltip>
        <TooltipTrigger
          render={
            <ThreadItemTimestamp
              dateTime={dateTime}
              className="shrink-0 text-[11px]"
            >
              {formatRelativeTimeShort(dateTime)}
            </ThreadItemTimestamp>
          }
        />
        <TooltipContent side="top">{formatTooltip(date)}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
