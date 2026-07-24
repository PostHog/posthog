import type { LoopSchemas } from "@posthog/api-client/loops";
import {
  buildChannelTargetValue,
  parseChannelIdFromTargetValue,
  parseChannelNameFromTargetValue,
} from "@posthog/core/settings/slackNotificationTarget";
import { Switch } from "@posthog/quill";
import { useIntegrationSelectors } from "@posthog/ui/features/integrations/store";
import { useSlackConnect } from "@posthog/ui/features/integrations/useSlackConnect";
import { SlackWorkspaceChannelPicker } from "@posthog/ui/features/settings/components/SlackWorkspaceChannelPicker";
import { Button } from "@posthog/ui/primitives/Button";
import { Checkbox, Flex, Text } from "@radix-ui/themes";

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
    <Flex direction="column" gap="3">
      <Text className="text-[12.5px] text-gray-10 leading-snug">
        Each run and its full output live on this loop's page. Notifications
        only send a short summary with a link when something happens.
      </Text>
      <NotificationChannelRow
        title="Push"
        description="Sends a push notification to the loop owner's devices with PostHog installed."
        channel={notifications.push}
        disabled={disabled}
        onChange={(patch) => updateChannel("push", patch)}
      />
      <NotificationChannelRow
        title="Email"
        description="Emails a run summary to the loop owner's account email."
        channel={notifications.email}
        disabled={disabled}
        onChange={(patch) => updateChannel("email", patch)}
      />
      <SlackNotificationRow
        channel={notifications.slack}
        disabled={disabled}
        onChange={(patch) => updateChannel("slack", patch)}
      />
    </Flex>
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
    <Flex
      direction="column"
      gap="2"
      className="rounded-(--radius-2) border border-border bg-(--gray-1) p-3"
    >
      <Flex align="center" justify="between" gap="2">
        <Flex direction="column" gap="0">
          <Text className="font-medium text-[13px] text-gray-12">{title}</Text>
          <Text className="text-[12px] text-gray-10">{description}</Text>
        </Flex>
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
      </Flex>

      {channel.enabled ? (
        <Flex direction="column" gap="2">
          <EventFilterCheckboxes
            events={channel.events}
            disabled={disabled}
            onChange={(events) => onChange({ events })}
          />
          {children}
        </Flex>
      ) : null}
    </Flex>
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
    <Flex direction="column" gap="1.5">
      <Text className="font-medium text-[12px] text-gray-11">Notify on</Text>
      <Flex gap="3" wrap="wrap">
        {EVENT_OPTIONS.map((option) => (
          <Text
            key={option.value}
            as="label"
            className="flex items-center gap-1.5 text-[12.5px] text-gray-12"
          >
            <Checkbox
              size="1"
              checked={events.includes(option.value)}
              disabled={disabled}
              onCheckedChange={(checked) =>
                toggle(option.value, checked === true)
              }
            />
            {option.label}
          </Text>
        ))}
      </Flex>
    </Flex>
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
      description="Posts a run summary to the channel you pick, through this project's Slack connection."
      channel={channel}
      disabled={disabled}
      onChange={onChange}
    >
      {!hasSlackIntegration ? (
        <Button
          variant="outline"
          size="1"
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
