import { ChartLineIcon, ClockIcon } from "@phosphor-icons/react";
import type {
  ReportCheckRowData,
  ReportCheckTone,
} from "@posthog/core/inbox/reportChecks";
import {
  Badge,
  Button,
  cn,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { Spinner } from "@posthog/ui/primitives/Spinner";

const BADGE_VARIANT: Record<
  ReportCheckTone,
  "default" | "info" | "success" | "destructive" | "warning"
> = {
  neutral: "default",
  info: "info",
  success: "success",
  danger: "destructive",
  warning: "warning",
};

/**
 * One follow-up check on the report detail: what it claims, where it stands, and the one thing a
 * reader can still do about it. Stop confirms first, because a cancelled check is terminal and
 * its author has to write a new one to get the answer back.
 */
export function ReportCheckRow({
  row,
  stopping,
  onStop,
}: {
  row: ReportCheckRowData;
  stopping: boolean;
  onStop: (check: ReportCheckRowData["check"]) => void;
}) {
  const { check, tag, detail, cancelled, cancellable } = row;
  const Icon = check.kind === "agent" ? ClockIcon : ChartLineIcon;

  return (
    <div
      className={cn(
        "flex flex-col gap-1 rounded-sm border border-border px-2.5 py-2",
        cancelled && "opacity-60",
      )}
    >
      <div className="flex min-w-0 items-start gap-2">
        <Icon
          size={13}
          className="mt-0.5 shrink-0 text-muted-foreground"
          aria-hidden="true"
        />
        {check.rationale ? (
          <Tooltip>
            <TooltipTrigger
              render={
                <span
                  className={cn(
                    "min-w-0 flex-1 text-left text-foreground text-xs leading-snug",
                    cancelled && "line-through",
                  )}
                />
              }
            >
              {check.title}
            </TooltipTrigger>
            <TooltipContent>{check.rationale}</TooltipContent>
          </Tooltip>
        ) : (
          <span
            className={cn(
              "min-w-0 flex-1 text-foreground text-xs leading-snug",
              cancelled && "line-through",
            )}
          >
            {check.title}
          </span>
        )}
        <Badge variant={BADGE_VARIANT[tag.tone]} className="shrink-0">
          {tag.label}
        </Badge>
      </div>
      <div className="flex min-w-0 items-end gap-2 pl-[1.3125rem]">
        <span className="min-w-0 flex-1 text-muted-foreground text-xs leading-snug">
          {detail}
        </span>
        {cancellable && (
          <Button
            variant="destructive-outline"
            size="xs"
            disabled={stopping}
            onClick={() => onStop(check)}
            className="shrink-0"
          >
            {stopping && <Spinner aria-hidden="true" />}
            {stopping ? "Stopping" : "Stop"}
          </Button>
        )}
      </div>
    </div>
  );
}
