import {
  ArrowSquareOutIcon,
  GearSixIcon,
  SparkleIcon,
} from "@phosphor-icons/react";
import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import {
  formatRunIntervalShort,
  prettifyScoutSkillName,
  type ScoutRollup,
  scoutSkillSlug,
} from "@posthog/core/scouts/scoutPresentation";
import { buildScoutCheckinPrompt } from "@posthog/core/scouts/scoutPrompts";
import type { ScoutSurface } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { track } from "@posthog/ui/shell/analytics";
import { skillUrl } from "@posthog/ui/utils/posthogLinks";
import { Box, Flex, Text, Tooltip } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useScoutChatTask } from "../hooks/useScoutChatTask";
import type { ScoutConfigUpdate } from "../hooks/useScoutConfigMutations";
import { DryRunBadge, ScoutOriginBadge } from "./ScoutBadges";
import { ScoutConfigForm, ScoutEnabledSwitch } from "./ScoutConfigControls";
import { ScoutRunBoxes } from "./ScoutRunBoxes";

/**
 * The one scout card: name, badges, cadence, emitted count, run boxes,
 * enable switch, and a gear that expands the settings form. Used as the fleet
 * list row; the scout detail screen builds its own header from the same parts.
 */
export function ScoutRowCard({
  config,
  rollup,
  onUpdate,
  linkToDetail = true,
}: {
  config: ScoutConfig;
  rollup: ScoutRollup | undefined;
  onUpdate: (configId: string, updates: ScoutConfigUpdate) => void;
  linkToDetail?: boolean;
}) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const cloudSkillUrl = skillUrl(config.skill_name);
  const surface: ScoutSurface = linkToDetail ? "fleet_list" : "scout_detail";

  const description = config.description?.trim();
  // `relative z-[1]` lifts the name above the Link's full-card `after:inset-0`
  // overlay so the tooltip's pointer-enter fires; clicks still bubble to the Link.
  const titleText = (
    <Text className="relative z-[1] truncate font-medium text-[13px] text-gray-12">
      {prettifyScoutSkillName(config.skill_name)}
    </Text>
  );
  const title = description ? (
    <Tooltip content={description}>{titleText}</Tooltip>
  ) : (
    titleText
  );

  return (
    <Flex
      direction="column"
      className={`group relative rounded-(--radius-3) border border-border bg-(--color-panel-solid) px-4 py-3 transition duration-150 hover:border-(--gray-6) hover:bg-(--gray-2) ${
        config.enabled ? "" : "opacity-65"
      }`}
    >
      <Flex align="center" gap="4">
        <Flex align="center" gap="2" className="min-w-0 flex-1">
          {linkToDetail ? (
            <Link
              to="/code/agents/scouts/$skillName"
              params={{ skillName: scoutSkillSlug(config.skill_name) }}
              className={`flex min-w-0 items-center gap-2 no-underline ${
                settingsOpen ? "" : "after:absolute after:inset-0"
              }`}
            >
              {title}
            </Link>
          ) : (
            <Flex align="center" gap="2" className="min-w-0">
              {title}
            </Flex>
          )}
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
                    surface,
                    skill_name: config.skill_name,
                  })
                }
                className="relative text-gray-9 transition-colors hover:text-accent-11"
              >
                <ArrowSquareOutIcon size={12} />
              </a>
            </Tooltip>
          ) : null}
          <ScoutOriginBadge config={config} />
          <DryRunBadge config={config} />
          <Text className="whitespace-nowrap text-[11px] text-gray-10">
            {formatRunIntervalShort(config.run_interval_minutes)}
          </Text>
          {rollup && rollup.emittedCount > 0 ? (
            <Text className="whitespace-nowrap text-[11px] text-gray-10">
              · {rollup.emittedCount} signal
              {rollup.emittedCount === 1 ? "" : "s"} emitted
            </Text>
          ) : null}
        </Flex>
        <Box className="relative shrink-0">
          <ScoutRunBoxes runs={rollup?.runs ?? []} />
        </Box>
        <Flex align="center" gap="3" className="relative shrink-0">
          <ScoutEnabledSwitch config={config} onUpdate={onUpdate} />
          <ScoutChatButton skillName={config.skill_name} surface={surface} />
          <Tooltip content="Scout settings">
            <button
              type="button"
              onClick={() => {
                const next = !settingsOpen;
                setSettingsOpen(next);
                track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                  action_type: next ? "open_settings" : "close_settings",
                  surface,
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
              <GearSixIcon size={14} />
            </button>
          </Tooltip>
        </Flex>
      </Flex>
      {settingsOpen ? (
        <Box className="mt-3 border-(--gray-4) border-t pt-3">
          <ScoutConfigForm config={config} onUpdate={onUpdate} />
        </Box>
      ) : null}
    </Flex>
  );
}

/**
 * Icon-only chat CTA on the row: fires a one-click auto-mode cloud task asking
 * the exploring-signals-scouts skill about this specific scout.
 */
export function ScoutChatButton({
  skillName,
  surface,
}: {
  skillName: string;
  surface: ScoutSurface;
}) {
  const prompt = useMemo(
    () => buildScoutCheckinPrompt(skillName, prettifyScoutSkillName(skillName)),
    [skillName],
  );
  const { runTask, isRunning } = useScoutChatTask({
    prompt,
    taskLabel: "scout check-in",
    loggerScope: "scout-checkin",
    chatType: "scout_checkin",
    surface,
    skillName,
  });
  return (
    <Tooltip content="Chat with PostHog about this scout">
      <button
        type="button"
        onClick={() => void runTask()}
        disabled={isRunning}
        aria-label={`Chat with PostHog about the ${skillName} scout`}
        className={`flex h-6 w-6 items-center justify-center rounded transition-colors disabled:cursor-default ${
          isRunning
            ? "animate-pulse text-(--iris-9)"
            : "text-gray-10 hover:bg-(--gray-3) hover:text-gray-12"
        }`}
      >
        <SparkleIcon size={14} />
      </button>
    </Tooltip>
  );
}
