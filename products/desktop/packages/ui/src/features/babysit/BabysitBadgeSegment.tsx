import { Eye, EyeSlash, Warning } from "@phosphor-icons/react";
import {
  Button,
  cn,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import {
  type BabysitUiState,
  useBabysitRunState,
  useStartBabysit,
  useStopBabysit,
} from "./useBabysitRunState";

interface BabysitBadgeSegmentProps {
  taskId: string;
  prUrl: string;
  variant?: "primary";
  toneClassName?: string;
}

type SegmentState = "on" | "needs_approval" | "off";

function toSegmentState(state: BabysitUiState): SegmentState | null {
  switch (state) {
    case "watching":
      return "on";
    case "attention":
      return "needs_approval";
    case "proposed":
    case "stopped":
    case "off":
      return "off";
    case "unavailable":
      return null;
  }
}

const SEGMENT_ICON: Record<SegmentState, React.ReactNode> = {
  on: <Eye size={14} />,
  needs_approval: <Warning size={14} />,
  off: <EyeSlash size={14} className="opacity-60" />,
};

const STATUS_LINE: Record<SegmentState, string> = {
  on: "Babysitting is on",
  needs_approval: "Waiting for your approval",
  off: "Babysitting is off",
};

export function BabysitBadgeSegment({
  taskId,
  prUrl,
  variant,
  toneClassName,
}: BabysitBadgeSegmentProps) {
  const { uiState, runId, staged, wakeUps } = useBabysitRunState(taskId, prUrl);
  const startBabysit = useStartBabysit(taskId, runId);
  const stopBabysit = useStopBabysit(taskId, runId);

  const state = toSegmentState(uiState);
  if (!state) return null;

  const busy = startBabysit.isPending || stopBabysit.isPending;
  const failingChecks = Array.isArray(
    (staged?.attention as { failing_checks?: unknown[] } | undefined)
      ?.failing_checks,
  )
    ? (staged?.attention as { failing_checks: unknown[] }).failing_checks.length
    : 0;

  const detail =
    state === "needs_approval"
      ? failingChecks > 0
        ? `${failingChecks} failing ${failingChecks === 1 ? "check" : "checks"}. The agent fixes them once you approve.`
        : "The PR needs a fix. The agent starts once you approve."
      : "The agent watches CI and reviews on this PR and fixes failures.";

  const statusLine =
    state === "on" && wakeUps > 0
      ? `${STATUS_LINE.on} · ${wakeUps} ${wakeUps === 1 ? "wake-up" : "wake-ups"}`
      : STATUS_LINE[state];

  return (
    <Popover>
      <Tooltip>
        <TooltipTrigger
          render={
            <PopoverTrigger
              render={
                <Button
                  size="sm"
                  variant={variant}
                  aria-label={STATUS_LINE[state]}
                  className={cn(
                    "px-2",
                    toneClassName,
                    state === "needs_approval" &&
                      "text-(--amber-11) [&_svg]:animate-pulse",
                  )}
                >
                  {SEGMENT_ICON[state]}
                </Button>
              }
            />
          }
        />
        <TooltipContent>{STATUS_LINE[state]}</TooltipContent>
      </Tooltip>
      <PopoverContent align="end" sideOffset={6} className="w-[260px] p-3">
        <Text className="block font-medium text-(--gray-12) text-sm">
          {statusLine}
        </Text>
        <Text className="mt-1 block text-(--gray-11) text-xs">{detail}</Text>
        <div className="mt-3 flex items-center justify-end gap-2">
          {(state === "on" || state === "needs_approval") && (
            <Button
              variant={state === "on" ? "outline" : "link-muted"}
              size="sm"
              disabled={busy}
              loading={stopBabysit.isPending}
              onClick={() => stopBabysit.mutate()}
            >
              Stop babysitting
            </Button>
          )}
          {state !== "on" && (
            <Button
              variant="primary"
              size="sm"
              disabled={busy}
              loading={startBabysit.isPending}
              onClick={() => startBabysit.mutate()}
            >
              {state === "needs_approval" ? "Approve" : "Start babysitting"}
            </Button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
