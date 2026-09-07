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
  formatScoutScheduleShort,
  hasPendingScoutRun,
  nextRunAt,
  prettifyScoutSkillName,
  runDurationSeconds,
  type ScoutRollup,
  type ScoutRunOutcome,
  scoutCreatorDisplayName,
  scoutRunOutcomeLabel,
  scoutSkillSlug,
} from "@posthog/core/scouts/scoutPresentation";
import {
  Avatar,
  AvatarFallback,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Skeleton,
  TableCell,
  TableRow,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useAgentsPageActions } from "@posthog/ui/features/agents/agentsPageStore";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { track } from "@posthog/ui/shell/analytics";
import { skillUrl } from "@posthog/ui/utils/posthogLinks";
import { memo } from "react";
import type { ScoutConfigUpdate } from "../hooks/useScoutConfigMutations";
import { useScoutRunNow } from "../hooks/useScoutRunNow";
import { AgentNameLink } from "./AgentNameLink";
import { DryRunBadge } from "./ScoutBadges";
import { ScoutEnabledSwitch } from "./ScoutConfigControls";
import { ScoutLifecycleBadge } from "./ScoutLifecycleBadges";
import { ScoutRunBoxes } from "./ScoutRunBoxes";

const ROW_BOXES = 18;
const PLACEHOLDER_BOXES = Array.from({ length: 14 }, (_, index) => index);

/** Holds the run column's ground while the run history is on its way. */
function RunBoxesPlaceholder() {
  return (
    <span className="flex animate-pulse items-center gap-1" aria-hidden>
      {PLACEHOLDER_BOXES.map((box) => (
        <span key={box} className="block h-3 w-2 rounded-[2px] bg-(--gray-3)" />
      ))}
    </span>
  );
}

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
  if (
    rollup?.runningRun &&
    deriveRunOutcome(rollup.runningRun, now) === "running"
  ) {
    return "bg-(--blue-9) shadow-[0_0_0_3px_var(--blue-a4)]";
  }
  if (lifecycle.isSystemPaused) return "border-[1.5px] border-(--amber-9)";
  if (!config.enabled) return "border-[1.5px] border-(--gray-7)";
  if (lifecycle.isWarned) return "bg-(--amber-9)";
  const latest = rollup?.latestRun;
  if (latest) {
    const outcome = deriveRunOutcome(latest, now);
    if (outcome === "error" || outcome === "timed_out" || outcome === "stuck")
      return "bg-(--red-9)";
  }
  return "bg-(--green-9)";
}

function ScoutTableRowInner({
  config,
  rollup,
  runsPending,
  creator,
  now,
  onUpdate,
  measureRef,
  index,
}: {
  config: ScoutConfig;
  rollup: ScoutRollup | undefined;
  /** Run history has not answered yet, so the runs column waits rather than reads empty. */
  runsPending: boolean;
  creator: LlmSkillCreatedBy | undefined;
  now: Date;
  onUpdate: (configId: string, updates: ScoutConfigUpdate) => void;
  /** Reports the rendered row height back to the virtualizer. */
  measureRef?: (node: HTMLTableRowElement | null) => void;
  index?: number;
}) {
  const { openAgent } = useAgentsPageActions();
  const { runNow, isStarting } = useScoutRunNow(config, "fleet_list");
  const slug = scoutSkillSlug(config.skill_name);
  const name = prettifyScoutSkillName(config.skill_name);
  const latest = rollup?.latestRun ?? null;
  const latestOutcome = latest ? deriveRunOutcome(latest, now) : null;
  const latestDuration = latest
    ? formatRunDuration(runDurationSeconds(latest, now))
    : "";
  const next = formatNextRun(nextRunAt(config, now), now);
  const cloudSkillUrl = skillUrl(config.skill_name);
  const dimmed =
    !config.enabled && !deriveScoutLifecycle(config).isSystemPaused;

  return (
    <TableRow
      ref={measureRef}
      data-index={index}
      className={dimmed ? "opacity-60" : undefined}
    >
      <TableCell className="py-2">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className={`inline-block h-2 w-2 shrink-0 rounded-full ${statusDotClass(config, rollup, now)}`}
            aria-hidden
          />
          <AgentNameLink
            config={config}
            onOpen={() => openAgent(slug)}
            dataAttr="scout-row-open"
          />
          <span className="sr-only @xl:not-sr-only @xl:contents">
            <DryRunBadge config={config} />
            <ScoutLifecycleBadge config={config} />
          </span>
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
            {formatScoutScheduleShort(config)}
          </span>
          {rollup?.runningRun &&
          deriveRunOutcome(rollup.runningRun, now) === "running" ? (
            <span className="text-(--blue-11) text-[11px]">running now</span>
          ) : next ? (
            <span className="text-[11px] text-gray-10">next {next}</span>
          ) : null}
        </div>
      </TableCell>

      <TableCell className="@4xl:table-cell hidden overflow-hidden">
        {rollup && rollup.runs.length > 0 ? (
          <ScoutRunBoxes runs={rollup.runs} max={ROW_BOXES} />
        ) : runsPending ? (
          <RunBoxesPlaceholder />
        ) : (
          <span className="text-[11px] text-gray-11">
            No recent runs loaded
          </span>
        )}
      </TableCell>

      <TableCell className="@2xl:table-cell hidden">
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
        ) : config.last_run_at ? (
          <RelativeTimestamp
            timestamp={config.last_run_at}
            className="text-[12.5px] text-gray-12"
          />
        ) : runsPending ? (
          <Skeleton className="h-4 w-24" />
        ) : (
          <span className="text-[11px] text-gray-11">—</span>
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
              disabled={isStarting || hasPendingScoutRun(rollup)}
              onClick={() => void runNow()}
            >
              <PlayIcon size={13} />
              Run now
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => openAgent(slug, { tab: "settings" })}
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

// The fleet can hold hundreds of agents. Rows re-render on every scroll frame
// without this, and each one re-derives its schedule, outcome and run boxes.
export const ScoutTableRow = memo(ScoutTableRowInner);
