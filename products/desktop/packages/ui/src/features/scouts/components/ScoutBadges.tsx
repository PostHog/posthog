import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import {
  deriveScoutLifecycle,
  getScoutOrigin,
} from "@posthog/core/scouts/scoutPresentation";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { Badge, Flex, Text, Tooltip } from "@radix-ui/themes";

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
 * Why a scout is stopped, or about to be. Renders nothing for the healthy
 * states — the enable switch already says whether a scout is on, so the badge
 * only appears when the system did something the user did not ask for.
 */
export function ScoutLifecycleBadge({ config }: { config: ScoutConfig }) {
  const lifecycle = deriveScoutLifecycle(config);
  if (!lifecycle.label) return null;
  return (
    <Tooltip content={lifecycle.explanation ?? lifecycle.label}>
      <Badge
        variant="soft"
        color={lifecycle.isSystemPaused ? "red" : "amber"}
        size="1"
        className="relative text-[11px]"
      >
        {lifecycle.label}
      </Badge>
    </Tooltip>
  );
}

/**
 * The full lifecycle story for surfaces with room for a sentence: what the
 * system did and what gets the scout running again. The fleet list makes do
 * with `ScoutLifecycleBadge`'s tooltip; this is for the scout detail screen.
 */
export function ScoutLifecycleNotice({ config }: { config: ScoutConfig }) {
  const lifecycle = deriveScoutLifecycle(config);
  if (!lifecycle.explanation) return null;
  return (
    <Flex
      align="center"
      gap="2"
      wrap="wrap"
      className={`rounded-(--radius-2) border px-3 py-2 ${
        lifecycle.isSystemPaused
          ? "border-(--red-6) bg-(--red-2)"
          : "border-(--amber-6) bg-(--amber-2)"
      }`}
    >
      <Text
        className={`text-[12.5px] leading-snug ${
          lifecycle.isSystemPaused ? "text-(--red-11)" : "text-(--amber-11)"
        }`}
      >
        {lifecycle.explanation}
      </Text>
      {lifecycle.changedAt ? (
        <RelativeTimestamp timestamp={lifecycle.changedAt} />
      ) : null}
    </Flex>
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
