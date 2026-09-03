import {
  ArrowSquareOutIcon,
  DotsThreeIcon,
  GearSixIcon,
  PlayIcon,
} from "@phosphor-icons/react";
import type {
  LlmSkillCreatedBy,
  ScoutConfig,
} from "@posthog/api-client/posthog-client";
import { getUserInitials } from "@posthog/core/auth/userInitials";
import {
  deriveRunOutcome,
  deriveScoutLifecycle,
  formatNextRun,
  formatRunDuration,
  formatRunInterval,
  nextRunAt,
  prettifyScoutSkillName,
  runDurationSeconds,
  type ScoutRollup,
  type ScoutRunOutcome,
  scoutCreatorDisplayName,
  scoutRunOutcomeLabel,
  scoutSkillSlug,
} from "@posthog/core/scouts/scoutPresentation";
import { SCOUT_RUNS_WINDOW_LABEL } from "@posthog/core/scouts/scoutRunsWindow";
import {
  Avatar,
  AvatarFallback,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  TableCell,
  TableRow,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { track } from "@posthog/ui/shell/analytics";
import { skillUrl } from "@posthog/ui/utils/posthogLinks";
import { Link, useNavigate } from "@tanstack/react-router";
import type { ScoutConfigUpdate } from "../hooks/useScoutConfigMutations";
import { useScoutRunNow } from "../hooks/useScoutRunNow";
import { DryRunBadge } from "./ScoutBadges";
import { ScoutEnabledSwitch } from "./ScoutConfigControls";
import { ScoutLifecycleBadge } from "./ScoutLifecycleBadges";
import { ScoutNameHoverCard } from "./ScoutNameHoverCard";
import { ScoutRunBoxes } from "./ScoutRunBoxes";

const ROW_BOXES = 24;

const OUTCOME_TEXT: Partial<Record<ScoutRunOutcome, string>> = {
  running: "text-(--blue-11)",
  stuck: "text-(--red-11)",
  error: "text-(--red-11)",
  timed_out: "text-(--amber-11)",
  emitted: "text-(--iris-11)",
};

function statusDotClass(
  config: ScoutConfig,
  rollup: ScoutRollup | undefined,
  now: Date,
): string {
  const lifecycle = deriveScoutLifecycle(config);
  if (rollup?.runningRun) {
    return "bg-(--blue-9) shadow-[0_0_0_3px_var(--blue-a4)]";
  }
  if (lifecycle.isSystemPaused) return "border-[1.5px] border-(--amber-9)";
  if (!config.enabled) return "border-[1.5px] border-(--gray-7)";
  if (lifecycle.isWarned) return "bg-(--amber-9)";
  const latest = rollup?.latestRun;
  if (latest) {
    const outcome = deriveRunOutcome(latest, now);
    if (outcome === "error" || outcome === "timed_out") return "bg-(--red-9)";
  }
  return "bg-(--green-9)";
}

export function ScoutTableRow({
  config,
  rollup,
  creator,
  now,
  onUpdate,
}: {
  config: ScoutConfig;
  rollup: ScoutRollup | undefined;
  creator: LlmSkillCreatedBy | undefined;
  now: Date;
  onUpdate: (configId: string, updates: ScoutConfigUpdate) => void;
}) {
  const navigate = useNavigate();
  const { runNow, isStarting } = useScoutRunNow(config, "fleet_list");
  const slug = scoutSkillSlug(config.skill_name);
  const name = prettifyScoutSkillName(config.skill_name);
  const latest = rollup?.latestRun ?? null;
  const latestOutcome = latest ? deriveRunOutcome(latest, now) : null;
  const latestDuration = latest
    ? formatRunDuration(runDurationSeconds(latest, now))
    : "";
  const next = formatNextRun(nextRunAt(config), now);
  const cloudSkillUrl = skillUrl(config.skill_name);
  const dimmed =
    !config.enabled && !deriveScoutLifecycle(config).isSystemPaused;

  return (
    <TableRow className={dimmed ? "opacity-60" : undefined}>
      <TableCell className="py-2">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className={`inline-block h-2 w-2 shrink-0 rounded-full ${statusDotClass(config, rollup, now)}`}
            aria-hidden
          />
          <ScoutNameHoverCard
            config={config}
            trigger={
              <Link
                to="/agents/scouts/$skillName"
                params={{ skillName: slug }}
                className="truncate font-medium text-[13px] text-gray-12 no-underline hover:underline"
                data-attr="scout-row-open"
              >
                {name}
              </Link>
            }
          />
          <DryRunBadge config={config} />
          <ScoutLifecycleBadge config={config} />
          {creator ? (
            <Tooltip content={`Created by ${scoutCreatorDisplayName(creator)}`}>
              <Avatar size="xs" className="ml-auto shrink-0">
                <AvatarFallback>{getUserInitials(creator)}</AvatarFallback>
              </Avatar>
            </Tooltip>
          ) : null}
        </div>
      </TableCell>

      <TableCell>
        <div className="flex flex-col gap-0.5 truncate">
          <span className="text-[12.5px] text-gray-12">
            {formatRunInterval(config.run_interval_minutes)}
          </span>
          {rollup?.runningRun ? (
            <span className="text-(--blue-11) text-[11px]">running now</span>
          ) : next ? (
            <span className="text-[11px] text-gray-10">next {next}</span>
          ) : null}
        </div>
      </TableCell>

      <TableCell>
        {rollup && rollup.runs.length > 0 ? (
          <ScoutRunBoxes runs={rollup.runs} max={ROW_BOXES} />
        ) : (
          <span className="text-[11px] text-gray-8">
            No runs in the {SCOUT_RUNS_WINDOW_LABEL}
          </span>
        )}
      </TableCell>

      <TableCell>
        {latest ? (
          <div className="flex flex-col gap-0.5 truncate">
            <RelativeTimestamp
              timestamp={latest.started_at}
              className="text-[12.5px] text-gray-12"
            />
            <span className="text-[11px] text-gray-10">
              <span
                className={
                  latestOutcome ? OUTCOME_TEXT[latestOutcome] : undefined
                }
              >
                {scoutRunOutcomeLabel(latest, now)}
              </span>
              {latestDuration ? ` · ${latestDuration}` : ""}
            </span>
          </div>
        ) : (
          <span className="text-[11px] text-gray-8">—</span>
        )}
      </TableCell>

      <TableCell>
        <ScoutEnabledSwitch config={config} onUpdate={onUpdate} />
      </TableCell>

      <TableCell>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                type="button"
                variant="default"
                size="icon-sm"
                aria-label={`${name} actions`}
                data-attr="scout-row-menu"
              >
                <DotsThreeIcon size={16} weight="bold" />
              </Button>
            }
          />
          <DropdownMenuContent align="end">
            <DropdownMenuItem
              disabled={isStarting || !config.enabled}
              onClick={() => void runNow()}
            >
              <PlayIcon size={13} />
              Run now
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() =>
                void navigate({
                  to: "/agents/scouts/$skillName",
                  params: { skillName: slug },
                  search: { tab: "settings" },
                })
              }
            >
              <GearSixIcon size={13} />
              Settings
            </DropdownMenuItem>
            {cloudSkillUrl ? (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => {
                    track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                      action_type: "open_skill_in_posthog",
                      surface: "fleet_list",
                      skill_name: config.skill_name,
                    });
                    window.open(cloudSkillUrl, "_blank", "noreferrer");
                  }}
                >
                  <ArrowSquareOutIcon size={13} />
                  Open skill in PostHog
                </DropdownMenuItem>
              </>
            ) : null}
          </DropdownMenuContent>
        </DropdownMenu>
      </TableCell>
    </TableRow>
  );
}
