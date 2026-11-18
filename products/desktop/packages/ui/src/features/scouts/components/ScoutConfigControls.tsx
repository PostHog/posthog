import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import {
  DEFAULT_SCOUT_DAILY_TIME,
  DEFAULT_SCOUT_WEEKLY_DAY,
  dailyCronToTime,
  dayTimeToWeeklyCron,
  deriveScoutLifecycle,
  formatNextRun,
  getScoutOrigin,
  getScoutScheduleMode,
  getScoutScheduleOptions,
  nextRunAt,
  SCOUT_CRON_MAX_LENGTH,
  SCOUT_CUSTOM_CRON_SCHEDULE_MODE,
  SCOUT_DAILY_AT_SCHEDULE_MODE,
  SCOUT_WEEKDAY_OPTIONS,
  SCOUT_WEEKLY_ON_SCHEDULE_MODE,
  scoutCronScheduleError,
  timeToDailyCron,
  weeklyCronToDayTime,
} from "@posthog/core/scouts/scoutPresentation";
import { Button, Input, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { RadioCards } from "@posthog/ui/primitives/RadioCards";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { track } from "@posthog/ui/shell/analytics";
import { skillUrl } from "@posthog/ui/utils/posthogLinks";
import { type ReactNode, useId, useState } from "react";
import type { ScoutConfigUpdate } from "../hooks/useScoutConfigMutations";
import { ScoutHelperSkillLinks } from "./ScoutHelperSkillLinks";

const MODE_OPTIONS = [
  {
    value: "live",
    title: "Live",
    description: "Signals reach Self-driving as soon as the agent finds them.",
  },
  {
    value: "dry_run",
    title: "Dry run",
    description:
      "Runs on schedule and records what it would send. Nothing leaves this page.",
  },
] as const;

interface ScoutConfigControlsProps {
  config: ScoutConfig;
  onUpdate: (configId: string, updates: ScoutConfigUpdate) => void;
}

export function ScoutEnabledSwitch({
  config,
  onUpdate,
}: ScoutConfigControlsProps) {
  // Switching a system-paused scout back on is the documented recovery, so say
  // "resume" rather than the generic "enable"; the badge beside it explains why
  // the scout stopped.
  const tooltip = config.enabled
    ? "Switch this agent off"
    : deriveScoutLifecycle(config).isSystemPaused
      ? "Resume this agent"
      : "Switch this agent on";
  return (
    <Tooltip content={tooltip}>
      <span className="inline-flex">
        <Switch
          size="sm"
          checked={config.enabled}
          onCheckedChange={(checked) =>
            onUpdate(config.id, { enabled: checked })
          }
          aria-label={`${config.skill_name} enabled`}
          data-attr="scout-enabled"
        />
      </span>
    </Tooltip>
  );
}

/** The Settings tab of the agent page. Every change saves as it is made. */
export function ScoutConfigForm({
  config,
  onUpdate,
}: ScoutConfigControlsProps) {
  const lifecycle = deriveScoutLifecycle(config);
  const cloudSkillUrl = skillUrl(config.skill_name);
  const next = formatNextRun(nextRunAt(config), new Date());
  const canonical = getScoutOrigin(config) === "canonical";
  const instructions = config.description?.trim();

  const weekly = weeklyCronToDayTime(config.run_cron_schedule);
  const runTime =
    dailyCronToTime(config.run_cron_schedule) ??
    weekly?.time ??
    DEFAULT_SCOUT_DAILY_TIME;
  const weeklyDay = weekly?.day ?? DEFAULT_SCOUT_WEEKLY_DAY;
  const savedScheduleMode = getScoutScheduleMode(config);
  // The saved config cannot express "the user opened the custom mode but has not typed a valid
  // expression yet", so that one pick is held here. Every other mode writes at once, so the config
  // stays the truth for them, including when a failed write rolls it back.
  const [customModePicked, setCustomModePicked] = useState(false);
  const scheduleMode = customModePicked
    ? SCOUT_CUSTOM_CRON_SCHEDULE_MODE
    : savedScheduleMode;

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-7">
      <SettingBlock
        title="Instructions"
        help={
          canonical
            ? "What this agent looks for. PostHog maintains built-in agents. To change one, ask PostHog to create a custom agent based on it."
            : "What this agent looks for. Edit the skill in PostHog to change what it watches and when it sends a signal."
        }
      >
        <div className="flex flex-col rounded-(--radius-md) border border-border bg-(--color-panel-solid)">
          {instructions ? (
            <p className="whitespace-pre-wrap px-3.5 py-3 text-[12.5px] text-gray-11 leading-relaxed">
              {instructions}
            </p>
          ) : (
            <p className="px-3.5 py-3 text-[12.5px] text-gray-10">
              This skill has no description.
            </p>
          )}
          <div className="flex items-center justify-between gap-3 border-(--gray-4) border-t px-3.5 py-2.5">
            <div className="flex min-w-0 flex-col gap-1">
              <code className="truncate text-[11.5px] text-gray-11">
                {config.skill_name}
              </code>
              <ScoutHelperSkillLinks surface="scout_detail" />
            </div>
            {cloudSkillUrl ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="shrink-0"
                onClick={() => {
                  track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                    action_type: "open_skill_in_posthog",
                    surface: "scout_detail",
                    skill_name: config.skill_name,
                  });
                  window.open(cloudSkillUrl, "_blank", "noreferrer");
                }}
              >
                <ArrowSquareOutIcon size={13} />
                {canonical ? "Open in PostHog" : "Edit in PostHog"}
              </Button>
            ) : null}
          </div>
        </div>
      </SettingBlock>

      <SettingBlock
        title="Mode"
        help="Use Dry run to check a new or changed agent before its signals reach anyone."
      >
        <RadioCards
          value={config.emit ? "live" : "dry_run"}
          options={MODE_OPTIONS}
          onChange={(value) => onUpdate(config.id, { emit: value === "live" })}
          ariaLabel={`${config.skill_name} mode`}
          dataAttrPrefix="scout-mode"
        />
      </SettingBlock>

      <SettingBlock
        title="Schedule"
        help={
          next
            ? `Next run ${next}. A schedule change applies immediately.`
            : "A rolling cadence, a set time each day or week, or a cron expression."
        }
      >
        <div className="flex flex-col gap-3 rounded-(--radius-md) border border-border bg-(--color-panel-solid) px-3.5 py-3">
          <SettingRow label="Cadence">
            <SettingsOptionSelect
              value={scheduleMode}
              options={getScoutScheduleOptions(config)}
              ariaLabel={`${config.skill_name} run interval`}
              disabled={!config.enabled}
              size="default"
              onValueChange={(value) => {
                setCustomModePicked(value === SCOUT_CUSTOM_CRON_SCHEDULE_MODE);
                if (
                  value === savedScheduleMode ||
                  value === SCOUT_CUSTOM_CRON_SCHEDULE_MODE
                ) {
                  return;
                }
                if (value === SCOUT_DAILY_AT_SCHEDULE_MODE) {
                  onUpdate(config.id, {
                    run_cron_schedule: timeToDailyCron(runTime),
                  });
                  return;
                }
                if (value === SCOUT_WEEKLY_ON_SCHEDULE_MODE) {
                  onUpdate(config.id, {
                    run_cron_schedule: dayTimeToWeeklyCron(weeklyDay, runTime),
                  });
                  return;
                }
                // A rolling cadence replaces any cron — the schedule is one or the other.
                onUpdate(config.id, {
                  run_interval_minutes: Number(value),
                  run_cron_schedule: null,
                });
              }}
            />
          </SettingRow>

          {scheduleMode === SCOUT_WEEKLY_ON_SCHEDULE_MODE ? (
            <SettingRow label="Run day" help="The agent runs once a week.">
              <SettingsOptionSelect
                value={weeklyDay}
                options={SCOUT_WEEKDAY_OPTIONS}
                ariaLabel={`${config.skill_name} run day`}
                disabled={!config.enabled}
                size="default"
                onValueChange={(day) =>
                  onUpdate(config.id, {
                    run_cron_schedule: dayTimeToWeeklyCron(day, runTime),
                  })
                }
              />
            </SettingRow>
          ) : null}

          {scheduleMode === SCOUT_DAILY_AT_SCHEDULE_MODE ||
          scheduleMode === SCOUT_WEEKLY_ON_SCHEDULE_MODE ? (
            <SettingRow label="Run time" help="Uses the project timezone.">
              <Input
                key={config.run_cron_schedule ?? "unset"}
                type="time"
                step={60}
                defaultValue={runTime}
                disabled={!config.enabled}
                aria-label={`${config.skill_name} run time`}
                onBlur={(event) => {
                  const value = event.currentTarget.value;
                  // Empty means a half-finished edit, never "clear" — switching the schedule
                  // off is the cadence picker's job, so fall back to the saved time.
                  if (!value) return;
                  const runCronSchedule =
                    scheduleMode === SCOUT_WEEKLY_ON_SCHEDULE_MODE
                      ? dayTimeToWeeklyCron(weeklyDay, value)
                      : timeToDailyCron(value);
                  if (runCronSchedule !== config.run_cron_schedule) {
                    onUpdate(config.id, { run_cron_schedule: runCronSchedule });
                  }
                }}
              />
            </SettingRow>
          ) : null}

          {scheduleMode === SCOUT_CUSTOM_CRON_SCHEDULE_MODE ? (
            <ScoutCustomCronField config={config} onUpdate={onUpdate} />
          ) : null}
        </div>
      </SettingBlock>

      {/* Null means the backend never sent the field, so a PATCH carrying it
          could not persist. Offer the control only where it writes. */}
      {lifecycle.autoPauseExempt !== null ? (
        <SettingBlock
          title="Auto-pause"
          help="PostHog can pause agents when nobody acts on their signals. Silence alone does not cause a pause. Repeated failures can pause an agent in either mode."
        >
          <div className="flex items-center justify-between gap-4 rounded-(--radius-md) border border-border bg-(--color-panel-solid) px-3.5 py-3">
            <span className="flex min-w-0 flex-col">
              <span className="text-[12.5px] text-gray-12">
                Never pause for inactivity
              </span>
              <span className="text-[11.5px] text-gray-10">
                For agents whose job is to stay quiet until something breaks.
              </span>
            </span>
            <Switch
              size="sm"
              checked={lifecycle.autoPauseExempt}
              onCheckedChange={(checked) =>
                onUpdate(config.id, { auto_pause_exempt: checked })
              }
              aria-label={`${config.skill_name} exempt from inactivity pauses`}
              data-attr="scout-auto-pause-exempt"
            />
          </div>
        </SettingBlock>
      ) : null}
    </div>
  );
}

/**
 * Raw cron editor for the schedule the presets cannot express — weekday runs, several days a
 * week, monthly. Validated against the same rules the config API applies, so a typo is caught
 * before the PATCH, and saved on blur or Enter.
 */
function ScoutCustomCronField({ config, onUpdate }: ScoutConfigControlsProps) {
  const errorId = useId();
  const [draft, setDraft] = useState(config.run_cron_schedule ?? "");
  const expression = draft.trim();
  // An empty field is a half-finished edit, not a mistake, so it stays neutral and saves nothing.
  const error = expression ? scoutCronScheduleError(expression) : null;
  const save = () => {
    if (!expression || error || expression === config.run_cron_schedule) return;
    onUpdate(config.id, { run_cron_schedule: expression });
  };

  return (
    <SettingRow
      label="Cron expression"
      help="Minute, hour, day of month, month, day of week, in the project timezone."
    >
      <div className="flex flex-col gap-1">
        <Input
          value={draft}
          placeholder="0 9 * * 1-5"
          maxLength={SCOUT_CRON_MAX_LENGTH}
          disabled={!config.enabled}
          className="font-mono"
          aria-label={`${config.skill_name} cron expression`}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          onChange={(event) => setDraft(event.currentTarget.value)}
          onBlur={save}
          onKeyDown={(event) => {
            if (event.key === "Enter") save();
          }}
        />
        {error ? (
          <span id={errorId} className="text-(--red-11) text-[11.5px]">
            {error}
          </span>
        ) : null}
      </div>
    </SettingRow>
  );
}

function SettingRow({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <span className="flex min-w-0 flex-col">
        <span className="text-[12.5px] text-gray-12">{label}</span>
        {help ? (
          <span className="text-[11.5px] text-gray-10">{help}</span>
        ) : null}
      </span>
      <div className="w-44 shrink-0">{children}</div>
    </div>
  );
}

function SettingBlock({
  title,
  help,
  children,
}: {
  title: string;
  help: string;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-col gap-0.5">
        <h2 className="font-semibold text-[13px] text-gray-12">{title}</h2>
        <p className="text-[11.5px] text-gray-10 leading-snug">{help}</p>
      </div>
      {children}
    </section>
  );
}
