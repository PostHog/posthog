import type { LoopSchemas } from "@posthog/api-client/loops";
import {
  buildChannelTargetValue,
  parseChannelIdFromTargetValue,
  parseChannelNameFromTargetValue,
} from "@posthog/core/settings/slackNotificationTarget";
import { Button, Checkbox, cn, Label, Switch } from "@posthog/quill";
import { useIntegrationSelectors } from "@posthog/ui/features/integrations/store";
import { useSlackConnect } from "@posthog/ui/features/integrations/useSlackConnect";
import { SlackWorkspaceChannelPicker } from "@posthog/ui/features/settings/components/SlackWorkspaceChannelPicker";

const EVENT_OPTIONS: {
  value: LoopSchemas.LoopNotificationEventEnum;
  label: string;
}[] = [
  { value: "run_completed", label: "Run completed" },
  { value: "run_failed", label: "Run failed" },
  { value: "pr_created", label: "PR created" },
  { value: "needs_attention", label: "Needs attention" },
];

const ALL_EVENTS = EVENT_OPTIONS.map((option) => option.value);

interface LoopNotificationsFieldsProps {
  notifications: LoopSchemas.LoopNotifications;
  onChange: (notifications: LoopSchemas.LoopNotifications) => void;
  disabled?: boolean;
}

export function LoopNotificationsFields({
  notifications,
  onChange,
  disabled,
}: LoopNotificationsFieldsProps) {
  const updateChannel = (
    channel: keyof LoopSchemas.LoopNotifications,
    patch: Partial<LoopSchemas.LoopNotificationChannel>,
  ) => {
    onChange({
      ...notifications,
      [channel]: { ...notifications[channel], ...patch },
    });
  };

  return (
    <div className="flex flex-col gap-3">
      <NotificationChannelRow
        title="Push"
        description="Owner devices"
        channel={notifications.push}
        disabled={disabled}
        onChange={(patch) => updateChannel("push", patch)}
      />
      <NotificationChannelRow
        title="Email"
        description="Owner account"
        channel={notifications.email}
        disabled={disabled}
        onChange={(patch) => updateChannel("email", patch)}
      />
      <SlackNotificationRow
        channel={notifications.slack}
        disabled={disabled}
        onChange={(patch) => updateChannel("slack", patch)}
      />
    </div>
  );
}

function NotificationChannelRow({
  title,
  description,
  channel,
  disabled,
  onChange,
  children,
}: {
  title: string;
  description: string;
  channel: LoopSchemas.LoopNotificationChannel;
  disabled?: boolean;
  onChange: (patch: Partial<LoopSchemas.LoopNotificationChannel>) => void;
  children?: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex flex-col",
        channel.enabled ? "gap-2" : "gap-0",
        "rounded-(--radius-2) border border-border bg-(--gray-1) px-3 py-2.5",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="font-medium text-[13px] text-gray-12">{title}</span>
          <span className="truncate text-[12px] text-gray-10">
            {description}
          </span>
        </div>
        <Switch
          checked={channel.enabled}
          disabled={disabled}
          aria-label={`${title} notifications`}
          onCheckedChange={(checked) =>
            onChange({
              enabled: checked,
              events:
                checked && channel.events.length === 0
                  ? ALL_EVENTS
                  : channel.events,
            })
          }
        />
      </div>

      {channel.enabled ? (
        <div className="flex flex-col gap-2 pt-2">
          <EventFilterCheckboxes
            events={channel.events}
            disabled={disabled}
            onChange={(events) => onChange({ events })}
          />
          {children}
        </div>
      ) : null}
    </div>
  );
}

function EventFilterCheckboxes({
  events,
  disabled,
  onChange,
}: {
  events: LoopSchemas.LoopNotificationEventEnum[];
  disabled?: boolean;
  onChange: (events: LoopSchemas.LoopNotificationEventEnum[]) => void;
}) {
  const toggle = (
    event: LoopSchemas.LoopNotificationEventEnum,
    checked: boolean,
  ) => {
    onChange(checked ? [...events, event] : events.filter((e) => e !== event));
  };

  return (
    <div className="flex flex-col gap-1.5">
      <span className="font-medium text-[12px] text-gray-11">Notify on</span>
      <div className="flex flex-wrap gap-3">
        {EVENT_OPTIONS.map((option) => (
          <Label
            className="flex items-center gap-1.5 text-[12.5px] text-gray-12"
            key={option.value}
          >
            <Checkbox
              checked={events.includes(option.value)}
              disabled={disabled}
              onCheckedChange={(checked) =>
                toggle(option.value, checked === true)
              }
            />
            {option.label}
          </Label>
        ))}
      </div>
    </div>
  );
}

interface SlackChannelParams {
  integration_id?: number;
  channel_id?: string;
  channel_name?: string;
  [key: string]: unknown;
}

function SlackNotificationRow({
  channel,
  disabled,
  onChange,
}: {
  channel: LoopSchemas.LoopNotificationChannel;
  disabled?: boolean;
  onChange: (patch: Partial<LoopSchemas.LoopNotificationChannel>) => void;
}) {
  const { hasSlackIntegration, slackIntegrations } = useIntegrationSelectors();
  const slackConnect = useSlackConnect();

  const params = channel.params as SlackChannelParams;
  const integrationId =
    params.integration_id ?? slackIntegrations[0]?.id ?? null;
  const channelTarget =
    params.channel_id && params.channel_name
      ? buildChannelTargetValue(params.channel_id, params.channel_name)
      : null;

  return (
    <NotificationChannelRow
      title="Slack"
      description="Channel summary"
      channel={channel}
      disabled={disabled}
      onChange={onChange}
    >
      {!hasSlackIntegration ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled || slackConnect.isConnecting}
          onClick={() => void slackConnect.connect()}
        >
          {slackConnect.isConnecting
            ? "Waiting for Slack…"
            : "Connect Slack workspace"}
        </Button>
      ) : (
        <SlackWorkspaceChannelPicker
          integrations={slackIntegrations}
          integrationId={integrationId}
          channelValue={channelTarget}
          channelAriaLabel="Slack channel"
          disabled={disabled}
          onIntegrationChange={(nextIntegrationId) => {
            const next: SlackChannelParams = {
              ...params,
              integration_id: nextIntegrationId,
            };
            delete next.channel_id;
            delete next.channel_name;
            onChange({ params: next });
          }}
          onChannelChange={(target) => {
            if (!target || !integrationId) {
              const next: SlackChannelParams = { ...params };
              delete next.channel_id;
              delete next.channel_name;
              onChange({ params: next });
              return;
            }
            onChange({
              params: {
                integration_id: integrationId,
                channel_id: parseChannelIdFromTargetValue(target),
                channel_name: parseChannelNameFromTargetValue(target),
              },
            });
          }}
        />
      )}
    </NotificationChannelRow>
  );
}
