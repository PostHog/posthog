import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { getScoutOrigin } from "@posthog/core/scouts/scoutPresentation";
import { Badge, Tooltip } from "@radix-ui/themes";
import type { ReactNode } from "react";

export function ScoutOriginBadge({ config }: { config: ScoutConfig }) {
  const origin = getScoutOrigin(config);
  return (
    <Tooltip
      content={
        origin === "canonical"
          ? "Part of the standard scout fleet built and maintained by PostHog"
          : "A scout your team created as a signals-scout-* skill in this project"
      }
    >
      <Badge
        variant="soft"
        color={origin === "canonical" ? "gray" : "iris"}
        size="1"
        className="relative text-[11px]"
      >
        {origin === "canonical" ? "Canonical" : "Custom"}
      </Badge>
    </Tooltip>
  );
}

export function DryRunBadge({ config }: { config: ScoutConfig }) {
  if (config.emit) return null;
  return (
    <Tooltip content="Runs on schedule but signals are not emitted to the Signals inbox">
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

/**
 * One scout tag. `children` is the optional trailing affordance — the tag editor
 * passes a remove button, read-only surfaces pass nothing.
 */
export function ScoutTagBadge({
  tag,
  children,
}: {
  tag: string;
  children?: ReactNode;
}) {
  return (
    <Badge
      variant="soft"
      color="iris"
      size="1"
      className="relative gap-1 text-[11px]"
    >
      {tag}
      {children}
    </Badge>
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
