import { ArrowSquareOutIcon, GearSixIcon } from "@phosphor-icons/react";
import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import {
  formatRunIntervalShort,
  type ScoutRollup,
} from "@posthog/core/scouts/scoutPresentation";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { track } from "@posthog/ui/shell/analytics";
import { skillUrl } from "@posthog/ui/utils/posthogLinks";
import { Box, Flex, Text, Tooltip } from "@radix-ui/themes";
import { useState } from "react";
import type { ScoutConfigUpdate } from "../hooks/useScoutConfigMutations";
import { DryRunBadge, ScoutOriginBadge } from "./ScoutBadges";
import { ScoutConfigForm, ScoutEnabledSwitch } from "./ScoutConfigControls";
import { ScoutChatButton } from "./ScoutRowCard";
import { ScoutRunBoxes } from "./ScoutRunBoxes";

/**
 * Header for the scout detail screen. Unlike the fleet-list `ScoutRowCard`,
 * this is not a card: the agent name, badges, skill link and cadence sit on the
 * page-title row with chat/settings/enable controls aligned right, then the
 * runs-window stats and the recent-runs boxes read as plain page content.
 */
export function ScoutDetailHeader({
  config,
  rollup,
  onUpdate,
  windowLabel,
  displayName,
  runsLoading,
}: {
  config: ScoutConfig;
  rollup: ScoutRollup | undefined;
  onUpdate: (configId: string, updates: ScoutConfigUpdate) => void;
  /** Label for the runs window (e.g. "last 3 days") shown in the stats line. */
  windowLabel: string;
  displayName: string;
  /** Runs load separately from the config; reserve the stats row while pending. */
  runsLoading: boolean;
}) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const cloudSkillUrl = skillUrl(config.skill_name);

  return (
    <Flex direction="column" gap="2">
      <Flex align="center" gap="2">
        <Text className="min-w-0 truncate font-bold text-[22px] text-gray-12 leading-tight tracking-tight">
          {displayName}
        </Text>
        <ScoutOriginBadge config={config} />
        <DryRunBadge config={config} />
        {cloudSkillUrl ? (
          <Tooltip content="View skill in PostHog">
            <a
              href={cloudSkillUrl}
              target="_blank"
              rel="noreferrer"
              aria-label={`${config.skill_name} skill in PostHog`}
              onClick={() =>
                track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                  action_type: "open_skill_in_posthog",
                  surface: "scout_detail",
                  skill_name: config.skill_name,
                })
              }
              className="text-gray-9 transition-colors hover:text-accent-11"
            >
              <ArrowSquareOutIcon size={14} />
            </a>
          </Tooltip>
        ) : null}
        <Text className="whitespace-nowrap text-[12px] text-gray-10">
          {formatRunIntervalShort(config.run_interval_minutes)}
        </Text>
        <span className="flex-1" />
        <ScoutChatButton skillName={config.skill_name} surface="scout_detail" />
        <Tooltip content="Scout settings">
          <button
            type="button"
            onClick={() => {
              const next = !settingsOpen;
              setSettingsOpen(next);
              track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                action_type: next ? "open_settings" : "close_settings",
                surface: "scout_detail",
                skill_name: config.skill_name,
              });
            }}
            aria-expanded={settingsOpen}
            aria-label={`${config.skill_name} settings`}
            className={`flex h-6 w-6 items-center justify-center rounded transition-colors ${
              settingsOpen
                ? "bg-(--gray-4) text-gray-12"
                : "text-gray-10 hover:bg-(--gray-3) hover:text-gray-12"
            }`}
          >
            <GearSixIcon size={15} />
          </button>
        </Tooltip>
        <ScoutEnabledSwitch config={config} onUpdate={onUpdate} />
      </Flex>

      {runsLoading ? (
        <Box className="h-[18px] w-80 max-w-full animate-pulse rounded bg-(--gray-3)" />
      ) : rollup && rollup.runCount > 0 ? (
        <Flex align="center" gap="3" wrap="wrap">
          <Text className="text-[12.5px] text-gray-11">
            {capitalize(windowLabel)}: {rollup.runCount} runs ·{" "}
            {rollup.completedCount} completed · {rollup.failedCount} failed ·{" "}
            {rollup.emittedCount} signal{rollup.emittedCount === 1 ? "" : "s"}{" "}
            emitted
          </Text>
          {rollup.runs.length > 0 ? <ScoutRunBoxes runs={rollup.runs} /> : null}
        </Flex>
      ) : null}

      {settingsOpen ? (
        <Box className="mt-1 border-(--gray-4) border-t pt-3">
          <ScoutConfigForm config={config} onUpdate={onUpdate} />
        </Box>
      ) : null}
    </Flex>
  );
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
