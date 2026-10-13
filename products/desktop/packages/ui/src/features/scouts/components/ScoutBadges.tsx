import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import {
  Badge,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";

export function DryRunBadge({ config }: { config: ScoutConfig }) {
  if (config.emit) return null;
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger
          render={
            <Badge variant="warning" className="relative text-[11px]">
              Dry run
            </Badge>
          }
        />
        <TooltipContent>
          Runs on schedule, but its signals do not reach Self-driving
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

const SEVERITY_COLORS: Record<string, "destructive" | "warning" | "default"> = {
  P0: "destructive",
  P1: "destructive",
  P2: "warning",
  P3: "warning",
  P4: "default",
};

export function SeverityBadge({ severity }: { severity: string | null }) {
  if (!severity) return null;
  return (
    <Badge
      variant={SEVERITY_COLORS[severity] ?? "default"}
      className="text-[11px]"
    >
      {severity}
    </Badge>
  );
}
