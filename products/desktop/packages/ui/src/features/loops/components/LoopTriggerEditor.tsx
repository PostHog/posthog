import {
  CalendarBlank,
  Clock,
  GithubLogo,
  Globe,
  Plus,
  Trash,
  Warning,
} from "@phosphor-icons/react";
import type { LoopSchemas } from "@posthog/api-client/loops";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemMenuItem,
  ItemTitle,
  Switch,
} from "@posthog/quill";
import { CopyButton } from "@posthog/ui/features/agent-applications/components/CopyButton";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { TimezonePicker } from "@posthog/ui/primitives/TimezonePicker";
import { TimezoneTimestamp } from "@posthog/ui/primitives/TimezoneTimestamp";
import {
  formatScheduleTimestamp,
  systemTimezone,
} from "@posthog/ui/primitives/timezone";
import { Box, Checkbox, Flex, IconButton, Text } from "@radix-ui/themes";
import type { ReactNode } from "react";
import {
  compileCronSchedule,
  DEFAULT_SCHEDULE_TIME,
  parseCronSchedule,
  type RecurringFrequency,
} from "../loopCron";
import { nextScheduleRun } from "../loopDisplay";
import {
  defaultLoopTriggerOfType,
  isTriggerDraftValid,
  type LoopTriggerDraft,
} from "../loopFormTypes";
import { LoopRepositoryPicker } from "./LoopRepositoryPicker";

const TRIGGER_TYPES: {
  type: LoopSchemas.LoopTriggerTypeEnum;
  label: string;
  subtitle: string;
  menuDescription: string;
  icon: typeof CalendarBlank;
}[] = [
  {
    type: "schedule",
    label: "Schedule",
    subtitle: "Runs at times you set",
    menuDescription: "Hourly, daily, weekly or once at a set time",
    icon: CalendarBlank,
  },
  {
    type: "github",
    label: "GitHub event",
    subtitle: "Runs on repository activity",
    menuDescription: "When a repo gets a push, PR or issue activity",
    icon: GithubLogo,
  },
  {
    type: "api",
    label: "API",
    subtitle: "Runs when your code calls an endpoint",
    menuDescription: "An authenticated POST from your own systems",
    icon: Globe,
  },
];

function triggerTypeMeta(type: LoopSchemas.LoopTriggerTypeEnum) {
  return TRIGGER_TYPES.find((t) => t.type === type) ?? TRIGGER_TYPES[0];
}

interface LoopTriggerEditorProps {
  triggers: LoopTriggerDraft[];
  onChange: (triggers: LoopTriggerDraft[]) => void;
  /** Rendered in the API trigger card. Absent for a not-yet-created loop. */
  triggerEndpointPath: string | null;
  disabled?: boolean;
}

export function LoopTriggerEditor({
  triggers,
  onChange,
  triggerEndpointPath,
  disabled,
}: LoopTriggerEditorProps) {
  const updateTrigger = (key: string, patch: Partial<LoopTriggerDraft>) => {
    onChange(
      triggers.map((trigger) =>
        trigger.key === key ? { ...trigger, ...patch } : trigger,
      ),
    );
  };

  const removeTrigger = (key: string) => {
    onChange(triggers.filter((trigger) => trigger.key !== key));
  };

  const addTrigger = (type: LoopSchemas.LoopTriggerTypeEnum) => {
    onChange([...triggers, defaultLoopTriggerOfType(type)]);
  };

  return (
    <Flex direction="column" gap="3">
      {triggers.length === 0 ? (
        <Empty className="py-8">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <CalendarBlank size={24} />
            </EmptyMedia>
            <EmptyTitle>No triggers</EmptyTitle>
            <EmptyDescription>
              This loop only runs when you start it from its page. Add a trigger
              to run it automatically.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        triggers.map((trigger) => (
          <TriggerCard
            key={trigger.key}
            trigger={trigger}
            triggerEndpointPath={triggerEndpointPath}
            disabled={disabled}
            onChange={(patch) => updateTrigger(trigger.key, patch)}
            onRemove={() => removeTrigger(trigger.key)}
          />
        ))
      )}

      <AddTriggerMenu disabled={disabled} onAdd={addTrigger} />
    </Flex>
  );
}

function AddTriggerMenu({
  disabled,
  onAdd,
}: {
  disabled?: boolean;
  onAdd: (type: LoopSchemas.LoopTriggerTypeEnum) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="outline"
            size="default"
            disabled={disabled}
            className="self-start text-[13px]"
          >
            <Plus size={13} />
            Add trigger
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="bottom"
        sideOffset={6}
        className="w-auto min-w-[280px]"
      >
        {TRIGGER_TYPES.map((option) => (
          <DropdownMenuItem
            key={option.type}
            onClick={() => onAdd(option.type)}
            render={
              <ItemMenuItem size="xs" className="w-full">
                <ItemMedia variant="icon" className="mt-2 ml-2">
                  <option.icon size={16} />
                </ItemMedia>
                <ItemContent variant="menuItem">
                  <ItemTitle>{option.label}</ItemTitle>
                  <ItemDescription className="whitespace-nowrap leading-none">
                    {option.menuDescription}
                  </ItemDescription>
                </ItemContent>
              </ItemMenuItem>
            }
          />
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function TriggerCard({
  trigger,
  triggerEndpointPath,
  disabled,
  onChange,
  onRemove,
}: {
  trigger: LoopTriggerDraft;
  triggerEndpointPath: string | null;
  disabled?: boolean;
  onChange: (patch: Partial<LoopTriggerDraft>) => void;
  onRemove: () => void;
}) {
  const meta = triggerTypeMeta(trigger.type);
  const Icon = meta.icon;
  const invalidMessage = isTriggerDraftValid(trigger)
    ? null
    : trigger.type === "github"
      ? "Pick a repository and at least one event to finish this trigger."
      : "Set when this trigger fires.";

  return (
    <Flex
      direction="column"
      className="overflow-hidden rounded-(--radius-3) border border-border bg-(--gray-1)"
    >
      <Flex align="center" gap="3" className="px-4 py-3">
        <Flex
          align="center"
          justify="center"
          className="size-8 shrink-0 rounded-(--radius-2) bg-(--gray-3)"
        >
          <Icon size={16} className="text-gray-11" />
        </Flex>
        <Flex direction="column" className="min-w-0 flex-1">
          <Text className="font-medium text-[13px] text-gray-12">
            {meta.label}
          </Text>
          <Text className="truncate text-[12px] text-gray-10">
            {meta.subtitle}
          </Text>
        </Flex>
        <Switch
          checked={trigger.enabled}
          onCheckedChange={(checked) => onChange({ enabled: checked })}
          disabled={disabled}
          aria-label={trigger.enabled ? "Disable trigger" : "Enable trigger"}
        />
        <IconButton
          variant="ghost"
          color="gray"
          size="1"
          aria-label="Remove trigger"
          disabled={disabled}
          onClick={onRemove}
        >
          <Trash size={15} />
        </IconButton>
      </Flex>

      <Box
        className={`border-border border-t px-4 py-4 ${
          trigger.enabled ? "" : "opacity-60"
        }`}
      >
        {trigger.type === "schedule" ? (
          <ScheduleTriggerFields
            config={trigger.config as LoopSchemas.LoopScheduleTriggerConfig}
            disabled={disabled}
            onChange={(config) => onChange({ config })}
          />
        ) : null}

        {trigger.type === "github" ? (
          <GithubTriggerFields
            config={trigger.config as LoopSchemas.LoopGithubTriggerConfig}
            disabled={disabled}
            onChange={(config) => onChange({ config })}
          />
        ) : null}

        {trigger.type === "api" ? (
          <ApiTriggerFields triggerEndpointPath={triggerEndpointPath} />
        ) : null}
      </Box>

      {invalidMessage ? (
        <Flex
          align="center"
          gap="2"
          className="border-border border-t px-4 py-2"
        >
          <Warning size={13} className="shrink-0 text-(--red-11)" />
          <Text className="text-(--red-11) text-[12px]">{invalidMessage}</Text>
        </Flex>
      ) : null}
    </Flex>
  );
}

function SubField({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Flex direction="column" gap="1" className={className}>
      <Text className="font-medium text-[12px] text-gray-11">{label}</Text>
      {children}
    </Flex>
  );
}

type ScheduleFrequency = RecurringFrequency | "once";

const FREQUENCY_OPTIONS: { value: ScheduleFrequency; label: string }[] = [
  { value: "hourly", label: "Hourly" },
  { value: "daily", label: "Daily" },
  { value: "weekdays", label: "Weekdays" },
  { value: "weekly", label: "Weekly" },
  { value: "once", label: "Once" },
];

const CUSTOM_FREQUENCY_OPTION = { value: "custom", label: "Custom" } as const;

const WEEKDAY_OPTIONS = [
  { value: "0", label: "Sunday" },
  { value: "1", label: "Monday" },
  { value: "2", label: "Tuesday" },
  { value: "3", label: "Wednesday" },
  { value: "4", label: "Thursday" },
  { value: "5", label: "Friday" },
  { value: "6", label: "Saturday" },
];

function ScheduleTriggerFields({
  config,
  disabled,
  onChange,
}: {
  config: LoopSchemas.LoopScheduleTriggerConfig;
  disabled?: boolean;
  onChange: (config: LoopSchemas.LoopScheduleTriggerConfig) => void;
}) {
  const parsed = parseCronSchedule(config.cron_expression);
  // A cron this picker didn't write (e.g. from the API or the loop builder)
  // renders as "Custom"; recompiling it into a picker shape would silently
  // replace the real schedule.
  const isCustomCron = !config.run_at && !!config.cron_expression && !parsed;
  const frequency: ScheduleFrequency | "custom" = config.run_at
    ? "once"
    : isCustomCron
      ? "custom"
      : (parsed?.frequency ?? "daily");
  const time = parsed?.time ?? DEFAULT_SCHEDULE_TIME;
  const weekday = parsed?.weekday ?? "1";
  const timezone = config.timezone ?? "UTC";
  const nextRun = nextScheduleRun(config);
  const nextRunTimezone = frequency === "once" ? systemTimezone() : timezone;
  const nextRunLabel = nextRun
    ? formatScheduleTimestamp(nextRun, nextRunTimezone)
    : null;
  const frequencyOptions = isCustomCron
    ? [CUSTOM_FREQUENCY_OPTION, ...FREQUENCY_OPTIONS]
    : FREQUENCY_OPTIONS;

  const setRecurring = (
    nextFrequency: RecurringFrequency,
    nextTime: string,
    nextWeekday: string,
  ) => {
    onChange({
      cron_expression: compileCronSchedule(
        nextFrequency,
        nextTime,
        nextWeekday,
      ),
      timezone,
    });
  };

  const handleFrequencyChange = (value: string) => {
    const next = value as ScheduleFrequency | "custom";
    if (next === "custom") return;
    if (next === "once") {
      // The backend rejects run_at values in the past; default an hour out.
      onChange({
        run_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
        timezone,
      });
      return;
    }
    setRecurring(next, time, weekday);
  };

  return (
    <Flex direction="column" gap="3">
      <Flex gap="3" wrap="wrap">
        <SubField label="Frequency" className="w-[150px]">
          <SettingsOptionSelect
            value={frequency}
            options={frequencyOptions}
            disabled={disabled}
            size="lg"
            ariaLabel="Frequency"
            onValueChange={handleFrequencyChange}
          />
        </SubField>

        {frequency === "daily" ||
        frequency === "weekdays" ||
        frequency === "weekly" ? (
          <SubField label="Time">
            <input
              type="time"
              disabled={disabled}
              value={time}
              className="h-8 rounded-(--radius-2) border border-border bg-transparent px-2.5 text-[13px] text-gray-12"
              onChange={(e) => {
                if (!e.target.value) return;
                setRecurring(frequency, e.target.value, weekday);
              }}
            />
          </SubField>
        ) : null}

        {frequency === "weekly" ? (
          <SubField label="Day" className="w-[150px]">
            <SettingsOptionSelect
              value={weekday}
              options={WEEKDAY_OPTIONS}
              disabled={disabled}
              size="lg"
              ariaLabel="Day of week"
              onValueChange={(value) => setRecurring("weekly", time, value)}
            />
          </SubField>
        ) : null}

        {frequency === "once" ? (
          <SubField label="Date and time">
            <input
              type="datetime-local"
              disabled={disabled}
              className="h-8 rounded-(--radius-2) border border-border bg-transparent px-2.5 text-[13px] text-gray-12"
              value={config.run_at ? toDatetimeLocal(config.run_at) : ""}
              onChange={(e) =>
                onChange({
                  run_at: e.target.value
                    ? new Date(e.target.value).toISOString()
                    : undefined,
                })
              }
            />
          </SubField>
        ) : null}
      </Flex>

      {frequency === "custom" ? (
        <Text className="self-start rounded-(--radius-1) border border-border bg-(--gray-2) px-2 py-1 text-[12px] text-gray-12 [font-family:var(--font-mono)]">
          {config.cron_expression}
        </Text>
      ) : null}

      {frequency !== "once" ? (
        <SubField label="Timezone">
          <TimezonePicker
            value={timezone}
            disabled={disabled}
            size="lg"
            className="w-[260px] max-w-full"
            onValueChange={(value) => onChange({ ...config, timezone: value })}
          />
        </SubField>
      ) : null}

      {nextRun && nextRunLabel ? (
        <Flex align="center" gap="2" className="text-[12px]">
          <Clock size={13} className="text-gray-10" />
          <Text className="text-gray-10">Next run</Text>
          <TimezoneTimestamp
            timestamp={nextRun}
            timezone={nextRunTimezone}
            label={nextRunLabel}
            className="text-gray-12"
          />
        </Flex>
      ) : null}
    </Flex>
  );
}

function toDatetimeLocal(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

const GITHUB_EVENT_OPTIONS: {
  value: LoopSchemas.LoopGithubTriggerEventEnum;
  label: string;
  description: string;
}[] = [
  {
    value: "push",
    label: "Push",
    description: "Commits are pushed to the repository",
  },
  {
    value: "pull_request",
    label: "Pull request activity",
    description: "A PR is opened, updated, merged or closed",
  },
  {
    value: "issues",
    label: "Issue activity",
    description: "An issue is opened, edited or closed",
  },
  {
    value: "issue_comment",
    label: "Issue comment",
    description: "A comment is added on an issue or PR",
  },
];

function GithubTriggerFields({
  config,
  disabled,
  onChange,
}: {
  config: LoopSchemas.LoopGithubTriggerConfig;
  disabled?: boolean;
  onChange: (config: LoopSchemas.LoopGithubTriggerConfig) => void;
}) {
  const toggleEvent = (
    event: LoopSchemas.LoopGithubTriggerEventEnum,
    checked: boolean,
  ) => {
    const events = checked
      ? [...config.events, event]
      : config.events.filter((e) => e !== event);
    onChange({ ...config, events });
  };

  return (
    <Flex direction="column" gap="3">
      <SubField label="Repository">
        <LoopRepositoryPicker
          value={
            config.repository
              ? {
                  github_integration_id: config.github_integration_id,
                  full_name: config.repository,
                }
              : null
          }
          disabled={disabled}
          onChange={(repo) =>
            onChange({
              ...config,
              repository: repo?.full_name ?? "",
              github_integration_id: repo?.github_integration_id ?? 0,
            })
          }
        />
      </SubField>

      <SubField label="Run when">
        <Flex direction="column" gap="2">
          {GITHUB_EVENT_OPTIONS.map((option) => (
            <Text
              key={option.value}
              as="label"
              className="flex items-start gap-2.5"
            >
              <Checkbox
                className="mt-0.5"
                checked={config.events.includes(option.value)}
                disabled={disabled}
                onCheckedChange={(checked) =>
                  toggleEvent(option.value, checked === true)
                }
              />
              <span className="flex flex-col">
                <span className="text-[13px] text-gray-12">{option.label}</span>
                <span className="text-[12px] text-gray-10">
                  {option.description}
                </span>
              </span>
            </Text>
          ))}
        </Flex>
      </SubField>
    </Flex>
  );
}

function ApiTriggerFields({
  triggerEndpointPath,
}: {
  triggerEndpointPath: string | null;
}) {
  return (
    <Flex direction="column" gap="3">
      <Text className="text-[12.5px] text-gray-11 leading-relaxed">
        Fires on an authenticated POST from your own code. Authenticate with a
        project secret API key (<code>phs_...</code>) scoped to{" "}
        <code>loop:write</code>. The request body becomes the run's trigger
        context.
      </Text>
      {triggerEndpointPath ? (
        <Flex
          align="center"
          justify="between"
          gap="2"
          className="rounded-(--radius-2) border border-border bg-(--gray-2) px-3 py-2"
        >
          <Text className="min-w-0 truncate text-[12px] text-gray-12 [font-family:var(--font-mono)]">
            POST {triggerEndpointPath}
          </Text>
          <CopyButton text={triggerEndpointPath} />
        </Flex>
      ) : (
        <Text className="text-[12px] text-gray-10">
          Save the loop to get its trigger URL.
        </Text>
      )}
    </Flex>
  );
}
