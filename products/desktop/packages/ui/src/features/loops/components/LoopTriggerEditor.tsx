import {
  CalendarBlank,
  Clock,
  DotsThreeVertical,
  GithubLogo,
  Globe,
  Plus,
  SlackLogo,
  Trash,
  Warning,
} from "@phosphor-icons/react";
import type { LoopSchemas } from "@posthog/api-client/loops";
import { parseChannelIdFromTargetValue } from "@posthog/core/settings/slackNotificationTarget";
import {
  Button,
  Chip,
  ChipClose,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Input,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemMenuItem,
  ItemTitle,
  Switch,
  ToggleGroup,
  ToggleGroupItem,
} from "@posthog/quill";
import { CopyButton } from "@posthog/ui/features/agent-applications/components/CopyButton";
import { useIntegrationSelectors } from "@posthog/ui/features/integrations/store";
import { useSlackConnect } from "@posthog/ui/features/integrations/useSlackConnect";
import { SlackWorkspaceChannelPicker } from "@posthog/ui/features/settings/components/SlackWorkspaceChannelPicker";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { TimezonePicker } from "@posthog/ui/primitives/TimezonePicker";
import { TimezoneTimestamp } from "@posthog/ui/primitives/TimezoneTimestamp";
import {
  formatScheduleTimestamp,
  systemTimezone,
} from "@posthog/ui/primitives/timezone";
import { Box, Checkbox, Flex, Text } from "@radix-ui/themes";
import { type ReactNode, useState } from "react";
import {
  compileCronSchedule,
  DEFAULT_SCHEDULE_TIME,
  parseCronSchedule,
  type RecurringFrequency,
} from "../loopCron";
import { nextScheduleRun } from "../loopDisplay";
import {
  defaultLoopTriggerOfType,
  githubTriggerActionOptions,
  isSlackActorId,
  isSlackChannelId,
  isTriggerDraftValid,
  type LoopTriggerDraft,
  withGithubTriggerEvents,
  withGithubTriggerFilters,
  withSlackTriggerFilters,
  withSlackTriggerPosterMode,
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
    type: "slack",
    label: "Slack message",
    subtitle: "Runs on messages in a channel",
    menuDescription: "When someone posts in a channel PostHog is in",
    icon: SlackLogo,
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

/** Names whichever half of the trigger is unfinished, so the disabled save button has a
 * reason. A blank condition row used to report the repository and events as missing. */
function githubTriggerInvalidMessage(
  config: LoopSchemas.LoopGithubTriggerConfig,
): string {
  if (
    !config.repository ||
    !config.github_integration_id ||
    !config.events.length
  ) {
    return "Pick a repository and at least one event to finish this trigger.";
  }
  return "Fill in a path and a value for each payload condition, or remove the empty rows.";
}

/** Names whichever half of the trigger is unfinished, so the disabled save button has a
 * reason. Channel IDs are checked separately because a pasted channel *name* looks filled
 * in but would never match anything Slack sends. */
function slackTriggerInvalidMessage(
  config: LoopSchemas.LoopSlackTriggerConfig,
): string {
  if (!config.slack_integration_id || config.channel_ids.length === 0) {
    return "Pick a Slack workspace and at least one channel to finish this trigger.";
  }
  const badChannel = config.channel_ids.find((id) => !isSlackChannelId(id));
  if (badChannel) {
    return `'${badChannel}' isn't a Slack channel ID. Use the ID, like C0123ABCDEF, not the channel name.`;
  }
  const posters = config.allowed_posters;
  if (
    posters?.mode === "slack_user_ids" &&
    (posters.slack_user_ids ?? []).length === 0
  ) {
    return "Add at least one Slack user, bot or app ID that's allowed to trigger this loop.";
  }
  const badActor = (posters?.slack_user_ids ?? []).find(
    (id) => !isSlackActorId(id),
  );
  if (badActor) {
    return `'${badActor}' isn't a Slack ID. Use a user ID (U…), bot ID (B…) or app ID (A…).`;
  }
  return "Fill in a path and a value for each message condition, or remove the empty rows.";
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
      ? githubTriggerInvalidMessage(
          trigger.config as LoopSchemas.LoopGithubTriggerConfig,
        )
      : trigger.type === "slack"
        ? slackTriggerInvalidMessage(
            trigger.config as LoopSchemas.LoopSlackTriggerConfig,
          )
        : "Set when this trigger fires.";

  return (
    <Flex
      direction="column"
      className="overflow-hidden rounded-(--radius-2) border border-border bg-(--gray-1)"
    >
      <Flex align="center" gap="2.5" className="px-3 py-2.5">
        <Flex
          align="center"
          justify="center"
          className="size-6 shrink-0 rounded-(--radius-1) bg-(--gray-3)"
        >
          <Icon size={14} className="text-gray-11" />
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
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                type="button"
                variant="link-muted"
                size="sm"
                disabled={disabled}
                aria-label="Trigger actions"
                className="text-gray-10"
              >
                <DotsThreeVertical size={16} weight="bold" />
              </Button>
            }
          />
          <DropdownMenuContent align="end" side="bottom" sideOffset={6}>
            <DropdownMenuItem
              onClick={onRemove}
              render={
                <ItemMenuItem size="xs" className="w-full text-(--red-11)">
                  <ItemMedia variant="icon" className="mt-2 ml-2">
                    <Trash size={15} />
                  </ItemMedia>
                  <ItemContent variant="menuItem">
                    <ItemTitle>Remove trigger</ItemTitle>
                  </ItemContent>
                </ItemMenuItem>
              }
            />
          </DropdownMenuContent>
        </DropdownMenu>
      </Flex>

      <Box
        className={`border-border border-t px-3 py-3 ${
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

        {trigger.type === "slack" ? (
          <SlackTriggerFields
            config={trigger.config as LoopSchemas.LoopSlackTriggerConfig}
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

/** Each accepted value is a discrete chip, committed with Enter. A single delimited text field
 * cannot represent a value that contains the delimiter, and the fields we match on (a PR title,
 * a team name, a Slack message phrase) legitimately contain commas. */
function ChipValues({
  values,
  ariaLabel,
  placeholder,
  disabled,
  onChange,
}: {
  values: string[];
  ariaLabel: string;
  placeholder: string;
  disabled?: boolean;
  onChange: (values: string[]) => void;
}) {
  const [draft, setDraft] = useState("");

  const commit = () => {
    const value = draft.trim();
    if (value && !values.includes(value)) {
      onChange([...values, value]);
    }
    setDraft("");
  };

  return (
    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1 rounded-(--radius-2) border border-border px-1.5 py-1">
      {values.map((value) => (
        <Chip key={value} size="sm" className="max-w-full">
          <span className="truncate">{value}</span>
          <ChipClose
            disabled={disabled}
            aria-label={`Remove ${value}`}
            onClick={() => onChange(values.filter((v) => v !== value))}
          />
        </Chip>
      ))}
      <input
        value={draft}
        disabled={disabled}
        placeholder={values.length === 0 ? placeholder : "Add value"}
        aria-label={ariaLabel}
        className="min-w-[80px] flex-1 bg-transparent text-[13px] text-gray-12 outline-none placeholder:text-gray-9"
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          }
          if (event.key === "Backspace" && !draft && values.length > 0) {
            onChange(values.slice(0, -1));
          }
        }}
      />
    </div>
  );
}

/** The `{path, equals}` condition rows shared by the github and slack triggers, which match
 * identically — a dot-path into the event body against a set of accepted values. */
function PayloadConditionRows({
  conditions,
  pathPlaceholder,
  valuePlaceholder,
  disabled,
  onChange,
}: {
  conditions: LoopSchemas.LoopGithubTriggerPayloadFilter[];
  pathPlaceholder: string;
  valuePlaceholder: string;
  disabled?: boolean;
  onChange: (conditions: LoopSchemas.LoopGithubTriggerPayloadFilter[]) => void;
}) {
  const updateCondition = (
    index: number,
    patch: Partial<LoopSchemas.LoopGithubTriggerPayloadFilter>,
  ) => {
    onChange(
      conditions.map((condition, i) =>
        i === index ? { ...condition, ...patch } : condition,
      ),
    );
  };

  return (
    <>
      {conditions.map((condition, index) => (
        <div
          // Keying on the path instead would remount the input on every keystroke.
          // biome-ignore lint/suspicious/noArrayIndexKey: rows carry no id and cannot be reordered, and both inputs are controlled off the config, so the index is a correct identity
          key={index}
          className="flex items-center gap-2"
        >
          <Input
            value={condition.path}
            disabled={disabled}
            placeholder={pathPlaceholder}
            // The placeholder stops naming the field as soon as someone types into it.
            aria-label="Condition path"
            className="h-7 flex-1"
            onChange={(event) =>
              updateCondition(index, { path: event.target.value })
            }
          />
          <span className="text-[12px] text-gray-10">is</span>
          <ChipValues
            values={
              Array.isArray(condition.equals)
                ? condition.equals
                : [condition.equals].filter(Boolean)
            }
            ariaLabel="Condition value"
            placeholder={valuePlaceholder}
            disabled={disabled}
            onChange={(equals) => updateCondition(index, { equals })}
          />
          <Button
            variant="outline"
            size="sm"
            disabled={disabled}
            aria-label={
              condition.path
                ? `Remove condition ${condition.path}`
                : "Remove condition"
            }
            onClick={() => onChange(conditions.filter((_, i) => i !== index))}
          >
            <Trash size={13} />
          </Button>
        </div>
      ))}
      <Button
        variant="outline"
        size="sm"
        disabled={disabled}
        className="self-start"
        onClick={() => onChange([...conditions, { path: "", equals: "" }])}
      >
        <Plus size={13} />
        Add condition
      </Button>
    </>
  );
}

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
    onChange(withGithubTriggerEvents(config, events));
  };

  const offerableActions = githubTriggerActionOptions(config.events);
  // A trigger set up through the API can hold an action we don't model, which would otherwise
  // render no chip: invisible, unremovable, and quietly narrowing the trigger.
  const actionOptions = [
    ...offerableActions,
    ...(config.filters?.actions ?? []).filter(
      (action) => !offerableActions.includes(action),
    ),
  ];
  const conditions = config.filters?.payload ?? [];

  const setConditions = (
    next: LoopSchemas.LoopGithubTriggerPayloadFilter[],
  ) => {
    onChange(withGithubTriggerFilters(config, { payload: next }));
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

      {actionOptions.length > 0 ? (
        <SubField label="Actions">
          <div className="flex flex-col gap-2">
            <span className="text-[12px] text-gray-10">
              Optional. Leave empty to run on every action.
            </span>
            <ToggleGroup
              multiple
              className="flex flex-wrap gap-1.5"
              value={config.filters?.actions ?? []}
              disabled={disabled}
              onValueChange={(actions: string[]) =>
                onChange(withGithubTriggerFilters(config, { actions }))
              }
            >
              {actionOptions.map((action) => (
                <ToggleGroupItem
                  key={action}
                  value={action}
                  size="sm"
                  variant="outline"
                  className="text-[12px] data-[pressed]:border-(--accent-9) data-[pressed]:bg-(--accent-3) data-[pressed]:text-(--accent-11)"
                >
                  {action}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
        </SubField>
      ) : null}

      <SubField label="Payload conditions">
        <div className="flex flex-col gap-2">
          <span className="text-[12px] text-gray-10">
            Optional. Match any other field in the GitHub payload, like{" "}
            <code>requested_team.slug</code> for the team asked to review.
          </span>
          <PayloadConditionRows
            conditions={conditions}
            pathPlaceholder="requested_team.slug"
            valuePlaceholder="team-security"
            disabled={disabled}
            onChange={setConditions}
          />
        </div>
      </SubField>
    </Flex>
  );
}

const SLACK_POSTER_OPTIONS: {
  value: LoopSchemas.LoopSlackPosterModeEnum;
  label: string;
}[] = [
  { value: "org_members", label: "Anyone on your team" },
  { value: "loop_owner", label: "Only me" },
  { value: "slack_user_ids", label: "Specific people or apps" },
];

const SLACK_POSTER_HINTS: Record<LoopSchemas.LoopSlackPosterModeEnum, string> =
  {
    org_members:
      "The person who posts has to have access to this project. Messages from apps and bots never match.",
    loop_owner:
      "Only your own messages start a run. Messages from apps and bots never match.",
    slack_user_ids:
      "The only option that can run on an alert posted by an app. Add the app's bot ID, or a teammate's user ID.",
  };

function SlackTriggerFields({
  config,
  disabled,
  onChange,
}: {
  config: LoopSchemas.LoopSlackTriggerConfig;
  disabled?: boolean;
  onChange: (config: LoopSchemas.LoopSlackTriggerConfig) => void;
}) {
  const { hasSlackIntegration, slackIntegrations } = useIntegrationSelectors();
  const slackConnect = useSlackConnect();

  const integrationId =
    config.slack_integration_id || slackIntegrations[0]?.id || null;
  const channelIds = config.channel_ids;
  const posterMode = config.allowed_posters?.mode ?? "org_members";
  const allowedIds = config.allowed_posters?.slack_user_ids ?? [];

  if (!hasSlackIntegration) {
    return (
      <Flex direction="column" gap="2" align="start">
        <Text className="text-[12.5px] text-gray-11 leading-relaxed">
          Connect a Slack workspace to run this loop from a channel.
        </Text>
        <Button
          variant="outline"
          size="default"
          disabled={disabled || slackConnect.isConnecting}
          onClick={() => void slackConnect.connect()}
        >
          {slackConnect.isConnecting
            ? "Waiting for Slack…"
            : "Connect Slack workspace"}
        </Button>
      </Flex>
    );
  }

  const addChannel = (target: string | null) => {
    if (!target || !integrationId) return;
    const channelId = parseChannelIdFromTargetValue(target);
    if (!channelId || channelIds.includes(channelId)) return;
    onChange({
      ...config,
      slack_integration_id: integrationId,
      channel_ids: [...channelIds, channelId],
    });
  };

  return (
    <Flex direction="column" gap="3">
      <SubField label="Channels">
        <div className="flex flex-col gap-2">
          <span className="text-[12px] text-gray-10">
            PostHog has to be in the channel to see its messages. Invite it with{" "}
            <code>/invite @PostHog</code>.
          </span>
          {channelIds.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1">
              {channelIds.map((channelId) => (
                <Chip key={channelId} size="sm" className="max-w-full">
                  <span className="truncate">{channelId}</span>
                  <ChipClose
                    disabled={disabled}
                    aria-label={`Remove ${channelId}`}
                    onClick={() =>
                      onChange({
                        ...config,
                        channel_ids: channelIds.filter(
                          (id) => id !== channelId,
                        ),
                      })
                    }
                  />
                </Chip>
              ))}
            </div>
          ) : null}
          <SlackWorkspaceChannelPicker
            // Remounts after each pick so the combobox returns to "Add a channel" rather
            // than sitting on the one just added.
            key={`${integrationId}-${channelIds.length}`}
            integrations={slackIntegrations}
            integrationId={integrationId}
            channelValue={null}
            channelAriaLabel="Add a channel"
            offLabel="Add a channel"
            disabled={disabled}
            onIntegrationChange={(nextIntegrationId) =>
              onChange({
                ...config,
                slack_integration_id: nextIntegrationId,
                // Channel ids belong to one workspace, so they can't survive the switch.
                channel_ids: [],
              })
            }
            onChannelChange={addChannel}
          />
        </div>
      </SubField>

      <SubField label="Keywords">
        <div className="flex flex-col gap-2">
          <span className="text-[12px] text-gray-10">
            Optional. Runs when the message contains any one of these, ignoring
            case. Leave empty to run on every message in the channel.
          </span>
          <ChipValues
            values={config.filters?.keywords ?? []}
            ariaLabel="Keyword"
            placeholder="incident"
            disabled={disabled}
            onChange={(keywords) =>
              onChange(withSlackTriggerFilters(config, { keywords }))
            }
          />
        </div>
      </SubField>

      <SubField label="Who can trigger it">
        <div className="flex flex-col gap-2">
          <span className="text-[12px] text-gray-10">
            The run uses your credentials, so this decides whose message can
            spend them.
          </span>
          <SettingsOptionSelect
            value={posterMode}
            options={SLACK_POSTER_OPTIONS}
            disabled={disabled}
            size="lg"
            ariaLabel="Who can trigger it"
            onValueChange={(value) =>
              onChange(
                withSlackTriggerPosterMode(
                  config,
                  value as LoopSchemas.LoopSlackPosterModeEnum,
                ),
              )
            }
          />
          <span className="text-[12px] text-gray-10">
            {SLACK_POSTER_HINTS[posterMode]}
          </span>
          {posterMode === "slack_user_ids" ? (
            <ChipValues
              values={allowedIds}
              ariaLabel="Slack ID"
              placeholder="B0123ABCDEF"
              disabled={disabled}
              onChange={(slack_user_ids) =>
                onChange({
                  ...config,
                  allowed_posters: { mode: posterMode, slack_user_ids },
                })
              }
            />
          ) : null}
        </div>
      </SubField>

      <SubField label="Message conditions">
        <div className="flex flex-col gap-2">
          <span className="text-[12px] text-gray-10">
            Optional. Match any other field on the Slack message, like{" "}
            <code>subtype</code>.
          </span>
          <PayloadConditionRows
            conditions={config.filters?.payload ?? []}
            pathPlaceholder="subtype"
            valuePlaceholder="file_share"
            disabled={disabled}
            onChange={(payload) =>
              onChange(withSlackTriggerFilters(config, { payload }))
            }
          />
        </div>
      </SubField>

      <Text className="text-[12px] text-gray-10">
        The run replies in a thread on the message that started it.
      </Text>
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
