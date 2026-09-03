import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import {
  DEFAULT_SCOUT_DAILY_TIME,
  DEFAULT_SCOUT_WEEKLY_DAY,
  dailyCronToTime,
  dayTimeToWeeklyCron,
  deriveScoutLifecycle,
  getScoutScheduleMode,
  getScoutScheduleOptions,
  SCOUT_CRON_MAX_LENGTH,
  SCOUT_CUSTOM_CRON_SCHEDULE_MODE,
  SCOUT_DAILY_AT_SCHEDULE_MODE,
  SCOUT_WEEKDAY_OPTIONS,
  SCOUT_WEEKLY_ON_SCHEDULE_MODE,
  scoutCronScheduleError,
  timeToDailyCron,
  weeklyCronToDayTime,
} from "@posthog/core/scouts/scoutPresentation";
import {
  Input as QuillInput,
  Switch as QuillSwitch,
  Text as QuillText,
} from "@posthog/quill";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { Flex, Switch, Text, Tooltip } from "@radix-ui/themes";
import { useId, useState } from "react";
import type { ScoutConfigUpdate } from "../hooks/useScoutConfigMutations";

const MODE_OPTIONS = [
  { value: "live", label: "Live" },
  { value: "dry_run", label: "Dry run" },
];

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
    ? "Disable scout"
    : deriveScoutLifecycle(config).isSystemPaused
      ? "Resume scout"
      : "Enable scout";
  return (
    <Tooltip content={tooltip}>
      {/* Tooltip stamps its own data-state on its child, which would overwrite
          the Switch's checked/unchecked state and leave the track stuck on the
          accent color. Give it a span to stamp. */}
      <span className="inline-flex">
        <Switch
          size="1"
          checked={config.enabled}
          onCheckedChange={(checked) =>
            onUpdate(config.id, { enabled: checked })
          }
          aria-label={`${config.skill_name} enabled`}
        />
      </span>
    </Tooltip>
  );
}

/**
 * Labeled settings form for one scout, shown when a fleet row's gear is
 * toggled open. Everything except enablement, which stays on the row.
 */
export function ScoutConfigForm({
  config,
  onUpdate,
}: ScoutConfigControlsProps) {
  const lifecycle = deriveScoutLifecycle(config);
  const weekly = weeklyCronToDayTime(config.run_cron_schedule);
  const runTime =
    dailyCronToTime(config.run_cron_schedule) ??
    weekly?.time ??
    DEFAULT_SCOUT_DAILY_TIME;
  const weeklyDay = weekly?.day ?? DEFAULT_SCOUT_WEEKLY_DAY;
  const savedScheduleMode = getScoutScheduleMode(config);
  // The saved config cannot express "the user opened the custom mode but has not typed a valid
  // expression yet", so the picked mode is held here until a write settles it.
  const [pickedScheduleMode, setPickedScheduleMode] = useState<string | null>(
    null,
  );
  const scheduleMode = pickedScheduleMode ?? savedScheduleMode;

  return (
    <Flex direction="column" gap="2">
      <Flex align="center" justify="between" gap="4">
        <Flex direction="column" className="min-w-0">
          <Text className="text-[12px] text-gray-12">Mode</Text>
          <Text className="text-[11.5px] text-gray-10">
            Dry run executes the scout but holds back its signals
          </Text>
        </Flex>
        <SettingsOptionSelect
          value={config.emit ? "live" : "dry_run"}
          options={MODE_OPTIONS}
          ariaLabel={`${config.skill_name} mode`}
          disabled={!config.enabled}
          className="w-24"
          onValueChange={(value) =>
            onUpdate(config.id, { emit: value === "live" })
          }
        />
      </Flex>
      <Flex align="center" justify="between" gap="4">
        <Flex direction="column" className="min-w-0">
          <Text className="text-[12px] text-gray-12">Cadence</Text>
          <Text className="text-[11.5px] text-gray-10">
            A rolling cadence, a set time each day or week, or a cron expression
          </Text>
        </Flex>
        <SettingsOptionSelect
          value={scheduleMode}
          options={getScoutScheduleOptions(config)}
          ariaLabel={`${config.skill_name} run interval`}
          disabled={!config.enabled}
          className="w-36"
          onValueChange={(value) => {
            setPickedScheduleMode(value);
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
      </Flex>
      {scheduleMode === SCOUT_WEEKLY_ON_SCHEDULE_MODE ? (
        <Flex align="center" justify="between" gap="4">
          <Flex direction="column" className="min-w-0">
            <Text className="text-[12px] text-gray-12">Run day</Text>
            <Text className="text-[11.5px] text-gray-10">
              The scout runs once a week, on this day
            </Text>
          </Flex>
          <SettingsOptionSelect
            value={weeklyDay}
            options={SCOUT_WEEKDAY_OPTIONS}
            ariaLabel={`${config.skill_name} run day`}
            disabled={!config.enabled}
            className="w-36"
            onValueChange={(day) =>
              onUpdate(config.id, {
                run_cron_schedule: dayTimeToWeeklyCron(day, runTime),
              })
            }
          />
        </Flex>
      ) : null}
      {scheduleMode === SCOUT_DAILY_AT_SCHEDULE_MODE ||
      scheduleMode === SCOUT_WEEKLY_ON_SCHEDULE_MODE ? (
        <Flex align="center" justify="between" gap="4">
          <Flex direction="column" className="min-w-0">
            <Text className="text-[12px] text-gray-12">Run time</Text>
            <Text className="text-[11.5px] text-gray-10">
              Uses the project timezone
            </Text>
          </Flex>
          <QuillInput
            key={config.run_cron_schedule ?? "unset"}
            type="time"
            step={60}
            defaultValue={runTime}
            disabled={!config.enabled}
            className="w-36"
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
        </Flex>
      ) : null}
      {scheduleMode === SCOUT_CUSTOM_CRON_SCHEDULE_MODE ? (
        <ScoutCustomCronField config={config} onUpdate={onUpdate} />
      ) : null}
      {/* Null means the backend never sent the field, so a PATCH carrying it
          could not persist. Offer the control only where it writes. */}
      {lifecycle.autoPauseExempt !== null ? (
        <div className="flex items-center justify-between gap-4">
          <div className="flex min-w-0 flex-col">
            <QuillText size="xs" className="text-gray-12">
              Never pause for inactivity
            </QuillText>
            <QuillText size="xxs" className="text-gray-10">
              Keep running when the scout goes quiet or its findings go unacted
              on. Repeated failures still pause it.
            </QuillText>
          </div>
          <QuillSwitch
            size="sm"
            checked={lifecycle.autoPauseExempt}
            onCheckedChange={(checked) =>
              onUpdate(config.id, { auto_pause_exempt: checked })
            }
            aria-label={`${config.skill_name} exempt from inactivity pauses`}
          />
        </div>
      ) : null}
    </Flex>
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
    <Flex align="start" justify="between" gap="4">
      <Flex direction="column" className="min-w-0">
        <Text className="text-[12px] text-gray-12">Cron expression</Text>
        <Text className="text-[11.5px] text-gray-10">
          Minute, hour, day of month, month, day of week, in the project
          timezone
        </Text>
      </Flex>
      <Flex direction="column" gap="1" className="w-36 shrink-0">
        <QuillInput
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
          <QuillText id={errorId} size="xxs" className="text-red-11">
            {error}
          </QuillText>
        ) : null}
      </Flex>
    </Flex>
  );
}
