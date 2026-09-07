import { ArrowLeftIcon, PlayIcon } from "@phosphor-icons/react";
import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import {
  SCOUT_DETAIL_TABS,
  type ScoutDetailTab,
} from "@posthog/core/scouts/scoutDetailTabs";
import {
  deriveRunOutcome,
  deriveScoutLifecycle,
  formatNextRun,
  formatRunDuration,
  formatScoutScheduleShort,
  getScoutOrigin,
  hasPendingScoutRun,
  nextRunAt,
  runDurationSeconds,
  type ScoutRollup,
  scoutCreatorDisplayName,
  scoutRunOutcomeLabel,
  scoutSummarySentence,
} from "@posthog/core/scouts/scoutPresentation";
import { Button, Skeleton } from "@posthog/quill";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { TabStrip } from "@posthog/ui/primitives/TabStrip";
import { Fragment, type ReactNode } from "react";
import type { ScoutConfigUpdate } from "../hooks/useScoutConfigMutations";
import { useScoutRunNow } from "../hooks/useScoutRunNow";
import { useScoutSkillCreators } from "../hooks/useScoutSkillCreators";
import { ScoutChatButton } from "./ScoutChatButton";
import { ScoutEnabledSwitch } from "./ScoutConfigControls";
import { ScoutHealthBanner } from "./ScoutLifecycleBadges";

const TAB_LABEL: Record<ScoutDetailTab, string> = {
  activity: "Activity",
  output: "Output",
  settings: "Settings",
};

const TABS = SCOUT_DETAIL_TABS.map((key) => ({ key, label: TAB_LABEL[key] }));

/**
 * Header for the agent page: name and health, one line on what it does, the
 * heartbeat (next run, last run), the actions, and the tab strip.
 */
export function ScoutDetailHeader({
  config,
  configLoading,
  displayName,
  rollup,
  onUpdate,
  tab,
  onTabChange,
  onBack,
}: {
  config: ScoutConfig | undefined;
  configLoading: boolean;
  displayName: string;
  rollup: ScoutRollup | undefined;
  onUpdate: (configId: string, updates: ScoutConfigUpdate) => void;
  tab: ScoutDetailTab;
  onTabChange: (tab: ScoutDetailTab) => void;
  onBack: () => void;
}) {
  return (
    <div className="flex shrink-0 cursor-default flex-col gap-3 border-(--gray-5) border-b px-6 pt-4">
      <button
        type="button"
        onClick={onBack}
        className="flex w-fit cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-[12px] text-gray-10 hover:text-gray-12"
        data-attr="scout-detail-back"
      >
        <ArrowLeftIcon size={12} />
        Agents
      </button>

      {configLoading || !config ? (
        <div className="flex flex-col gap-2">
          <span className="font-bold text-[22px] text-gray-12 leading-tight tracking-tight">
            {displayName}
          </span>
          {configLoading ? <Skeleton className="h-4 w-80" /> : null}
        </div>
      ) : (
        <ScoutDetailHeading
          config={config}
          displayName={displayName}
          rollup={rollup}
          onUpdate={onUpdate}
          onShowTab={onTabChange}
        />
      )}

      <TabStrip
        tabs={TABS}
        value={tab}
        onValueChange={onTabChange}
        dataAttrPrefix="scout-tab"
        className="-mb-px min-w-0 overflow-x-auto"
      />
    </div>
  );
}

function ScoutDetailHeading({
  config,
  displayName,
  rollup,
  onUpdate,
  onShowTab,
}: {
  config: ScoutConfig;
  displayName: string;
  rollup: ScoutRollup | undefined;
  onUpdate: (configId: string, updates: ScoutConfigUpdate) => void;
  onShowTab: (tab: ScoutDetailTab) => void;
}) {
  const now = new Date();
  const { runNow, isStarting } = useScoutRunNow(config, "scout_detail");
  const { data: creators } = useScoutSkillCreators();
  const creator = creators?.get(config.skill_name);
  const summary = scoutSummarySentence(config.description);
  const latest = rollup?.latestRun ?? null;
  const pendingRun = rollup?.runningRun;
  const running =
    pendingRun && deriveRunOutcome(pendingRun, now) === "running"
      ? pendingRun
      : null;
  const next = formatNextRun(nextRunAt(config, now), now);
  const latestDuration = latest
    ? formatRunDuration(runDurationSeconds(latest, now))
    : "";
  const latestOutcome = latest ? deriveRunOutcome(latest, now) : null;
  const origin = getScoutOrigin(config) === "canonical" ? "Built in" : "Custom";

  const meta: ReactNode[] = [
    creator ? `${origin} · by ${scoutCreatorDisplayName(creator)}` : origin,
  ];
  if (!config.emit) meta.push("Dry run");
  meta.push(formatScoutScheduleShort(config));
  if (running) {
    meta.push(
      <span className="text-(--blue-11)">
        Running now
        {running.started_at ? (
          <>
            , started{" "}
            <RelativeTimestamp
              timestamp={running.started_at}
              className="text-(--blue-11) text-[12px]"
            />
          </>
        ) : null}
      </span>,
    );
  } else if (next) {
    meta.push(
      <>
        Next run <span className="text-gray-12">{next}</span>
      </>,
    );
  } else {
    meta.push(
      !config.enabled
        ? "Switched off"
        : config.run_cron_schedule
          ? "Uses the project timezone"
          : "Next run time is unavailable",
    );
  }
  if (latest && latestOutcome !== "running") {
    meta.push(
      <>
        Last run{" "}
        <RelativeTimestamp
          timestamp={latest.started_at}
          className="text-[12px] text-gray-12"
        />
        {latestDuration ? `, ${latestDuration}` : ""}
        {", "}
        <span
          className={
            latestOutcome === "error" || latestOutcome === "stuck"
              ? "text-(--red-11)"
              : latestOutcome === "timed_out"
                ? "text-(--amber-11)"
                : undefined
          }
        >
          {scoutRunOutcomeLabel(latest, now)}
        </span>
      </>,
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start gap-4">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex min-w-0 items-center gap-2.5">
            <h1 className="min-w-0 truncate font-bold text-[22px] text-gray-12 leading-tight tracking-tight">
              {displayName}
            </h1>
            <HealthMark config={config} running={Boolean(running)} />
          </div>
          <p className="flex flex-wrap items-center gap-x-1.5 text-[12px] text-gray-10">
            {meta.map((item, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: static list built per render
              <Fragment key={index}>
                {index > 0 ? <span className="text-gray-8">·</span> : null}
                <span>{item}</span>
              </Fragment>
            ))}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void runNow()}
            disabled={isStarting || hasPendingScoutRun(rollup)}
            data-attr="scout-run-now"
          >
            <PlayIcon size={13} />
            {isStarting ? "Starting…" : running ? "Running" : "Run now"}
          </Button>
          <ScoutChatButton
            skillName={config.skill_name}
            surface="scout_detail"
            label="Discuss"
          />
          <ScoutEnabledSwitch config={config} onUpdate={onUpdate} />
        </div>
      </div>

      {summary ? (
        <p className="flex max-w-3xl flex-wrap items-baseline gap-x-2 text-[13px] text-gray-11 leading-snug">
          <span className="min-w-0">{summary}</span>
          <Button
            type="button"
            variant="link-muted"
            size="xs"
            className="h-auto px-0"
            onClick={() => onShowTab("settings")}
            data-attr="scout-open-instructions"
          >
            Read instructions
          </Button>
        </p>
      ) : null}

      <ScoutHealthBanner
        config={config}
        onUpdate={onUpdate}
        onShowTab={onShowTab}
      />
    </div>
  );
}

/** One word on the agent's state. Nothing when it is on and healthy. */
function HealthMark({
  config,
  running,
}: {
  config: ScoutConfig;
  running: boolean;
}) {
  const lifecycle = deriveScoutLifecycle(config);
  const mark = running
    ? {
        dot: "bg-(--blue-9) animate-pulse",
        text: "text-(--blue-11)",
        label: "Running",
      }
    : lifecycle.isSystemPaused
      ? { dot: "bg-(--red-9)", text: "text-(--red-11)", label: lifecycle.label }
      : lifecycle.isWarned
        ? {
            dot: "bg-(--amber-9)",
            text: "text-(--amber-11)",
            label: lifecycle.label,
          }
        : !config.enabled
          ? {
              dot: "border-[1.5px] border-(--gray-8)",
              text: "text-gray-10",
              label: "Off",
            }
          : null;
  if (!mark) return null;
  return (
    <span
      className={`flex shrink-0 items-center gap-1.5 font-medium text-[12px] ${mark.text}`}
    >
      <span
        className={`inline-block h-2 w-2 rounded-full ${mark.dot}`}
        aria-hidden
      />
      {mark.label}
    </span>
  );
}
