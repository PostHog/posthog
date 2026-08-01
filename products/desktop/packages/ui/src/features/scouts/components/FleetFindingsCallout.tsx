import { ArrowRightIcon, SparkleIcon } from "@phosphor-icons/react";
import { summarizeEmittedRuns } from "@posthog/core/scouts/scoutFindings";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { navigateToScoutFindings } from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { Flex, Text } from "@radix-ui/themes";
import { useMemo } from "react";
import { useScoutRuns } from "../hooks/useScoutRuns";

/**
 * Findings entry point for the scout fleet section. Advertises the troop's recent
 * findings (count · scouts · recency) and links into the cross-fleet findings
 * page. Reads the cheap runs-window summary so it never triggers the per-run
 * emissions fetch the page does on open. Renders nothing until there's at least
 * one finding.
 *
 * Mirrors the PostHog Cloud `FleetFindingsCallout`.
 */
export function FleetFindingsCallout() {
  const { data: runsWindow, isLoading } = useScoutRuns();
  const summary = useMemo(
    () => summarizeEmittedRuns(runsWindow?.runs ?? []),
    [runsWindow],
  );

  // Hold until the first runs load settles, then only show when there's
  // something to read.
  if (isLoading || summary.totalCount === 0) {
    return null;
  }

  return (
    <button
      type="button"
      onClick={() => {
        track(ANALYTICS_EVENTS.SCOUT_ACTION, {
          action_type: "open_findings",
          surface: "fleet_list",
        });
        navigateToScoutFindings();
      }}
      className="flex w-full items-center gap-3 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-4 py-3.5 text-left transition-colors duration-150 hover:border-(--gray-6) hover:bg-(--gray-2)"
    >
      <SparkleIcon size={20} className="shrink-0 text-(--iris-9)" />
      <Flex direction="column" gap="0" className="min-w-0">
        <Text className="font-medium text-[13px] text-gray-12">
          Scout findings
        </Text>
        <Text className="truncate text-[12px] text-gray-11 leading-snug">
          {summary.totalCount} finding{summary.totalCount === 1 ? "" : "s"}{" "}
          across {summary.scoutCount} scout
          {summary.scoutCount === 1 ? "" : "s"}
          {summary.latestEmittedAt ? (
            <>
              {" · latest "}
              <RelativeTimestamp
                timestamp={summary.latestEmittedAt}
                className="inline text-[12px] text-gray-11"
              />
            </>
          ) : null}
        </Text>
      </Flex>
      <span className="flex-1" />
      <ArrowRightIcon size={14} className="shrink-0 text-gray-10" />
    </button>
  );
}
