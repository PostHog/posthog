import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { Badge, Tooltip } from "@radix-ui/themes";

export function DryRunBadge({ config }: { config: ScoutConfig }) {
  if (config.emit) return null;
  return (
    <Tooltip content="Runs on schedule, but its signals do not reach Self-driving">
      <Badge
        variant="soft"
        color="amber"
        size="1"
        className="relative text-[11px]"
      >
        Dry run
      </Badge>
    </Tooltip>
  );
}

const SEVERITY_COLORS: Record<string, "red" | "orange" | "amber" | "gray"> = {
  P0: "red",
  P1: "red",
  P2: "orange",
  P3: "amber",
  P4: "gray",
};

export function SeverityBadge({ severity }: { severity: string | null }) {
  if (!severity) return null;
  return (
    <Badge
      variant="soft"
      color={SEVERITY_COLORS[severity] ?? "gray"}
      size="1"
      className="text-[11px]"
    >
      {severity}
    </Badge>
  );
}
