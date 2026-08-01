import { Button } from "@posthog/quill";
import type { SignalReportPriority } from "@posthog/shared/domain-types";
import { useSignalSourceManager } from "@posthog/ui/features/inbox/hooks/useSignalSourceManager";
import { useIntegrationSelectors } from "@posthog/ui/features/integrations/store";
import { useSlackConnect } from "@posthog/ui/features/integrations/useSlackConnect";
import { SlackChannelCombobox } from "@posthog/ui/features/settings/components/SlackChannelCombobox";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { Box, Callout, Flex, Text } from "@radix-ui/themes";

const NOTIFY_ALL_VALUE = "__all__";

const MIN_PRIORITY_OPTIONS: {
  value: SignalReportPriority | typeof NOTIFY_ALL_VALUE;
  label: string;
}[] = [
  { value: NOTIFY_ALL_VALUE, label: "All priorities" },
  { value: "P0", label: "P0 only" },
  { value: "P1", label: "P1 and above" },
  { value: "P2", label: "P2 and above" },
  { value: "P3", label: "P3 and above" },
  { value: "P4", label: "P4 and above" },
];

const SETTINGS_CONTROL_CLASS = "min-w-[200px] max-w-[240px]";

interface SignalSlackNotificationsSettingsProps {
  /** Workspace whose channels are listed — shared with the team default. */
  integrationId: number | null;
  channelComboboxModal?: boolean;
  isLoading?: boolean;
  /** When false, omit the dashed top rule (e.g. inside a parent `divide-y` list). */
  showTopBorder?: boolean;
  /** When true, omit the connect-workspace prompt (shown by a parent section). */
  hideWorkspaceConnect?: boolean;
}

export function SignalSlackNotificationsSettings({
  integrationId,
  channelComboboxModal = false,
  isLoading = false,
  showTopBorder = true,
  hideWorkspaceConnect = false,
}: SignalSlackNotificationsSettingsProps) {
  const topBorderClass = showTopBorder
    ? "border-(--gray-5) border-t border-dashed pt-4"
    : "";
  const { hasSlackIntegration } = useIntegrationSelectors();
  const { userAutonomyConfig, handleUpdateSlackNotifications } =
    useSignalSourceManager();
  const slackConnect = useSlackConnect();

  const selectedChannelTarget =
    userAutonomyConfig?.slack_notification_channel ?? null;
  const minPriority =
    userAutonomyConfig?.slack_notification_min_priority ?? null;

  const notificationsEnabled = !!integrationId && !!selectedChannelTarget;

  if (isLoading) {
    return (
      <Flex direction="column" gap="2" className={topBorderClass}>
        <Flex direction="column" gap="1">
          <Box className="h-[14px] w-[160px] animate-pulse rounded bg-gray-4" />
          <Box className="h-[11px] w-[80%] animate-pulse rounded bg-gray-3" />
        </Flex>
        <Box className="mt-1 h-[28px] w-[200px] animate-pulse rounded bg-gray-3" />
      </Flex>
    );
  }

  if (!hasSlackIntegration) {
    if (hideWorkspaceConnect) {
      return null;
    }

    return (
      <Flex direction="column" gap="2" className={topBorderClass}>
        <Flex direction="column" gap="1">
          <Text className="font-medium text-(--gray-12) text-sm">
            Notify me directly
          </Text>
          <Text className="text-(--gray-11) text-[13px]">
            Get pinged in your own channel when you're a suggested reviewer on a
            new inbox item.
          </Text>
        </Flex>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={slackConnect.isConnecting}
          onClick={() => {
            void slackConnect.connect();
          }}
          className="w-fit"
        >
          {slackConnect.isConnecting
            ? "Waiting for Slack…"
            : "Connect Slack workspace"}
        </Button>
        {slackConnect.hasError && slackConnect.error ? (
          <Callout.Root size="1" color="red" variant="soft">
            <Callout.Text>{slackConnect.error.message}</Callout.Text>
          </Callout.Root>
        ) : null}
        {slackConnect.isTimedOut ? (
          <Callout.Root size="1" color="gray" variant="soft">
            <Callout.Text>
              We didn't hear back from PostHog. If you completed the connection
              in your browser it should appear shortly, otherwise try again.
            </Callout.Text>
          </Callout.Root>
        ) : null}
      </Flex>
    );
  }

  const onChannelChange = (channel: string | null) => {
    if (channel === null) {
      void handleUpdateSlackNotifications({ channel: null });
      return;
    }
    if (!integrationId) return;
    void handleUpdateSlackNotifications({ integrationId, channel });
  };

  const onMinPriorityChange = (value: string) => {
    void handleUpdateSlackNotifications({
      minPriority: value === NOTIFY_ALL_VALUE ? null : value,
    });
  };

  return (
    <Flex direction="column" gap="2" className={topBorderClass}>
      <Flex direction="column" gap="1">
        <Text className="font-medium text-(--gray-12) text-sm">
          Notify me directly
        </Text>
        <Text className="text-(--gray-11) text-[13px]">
          When you're a suggested reviewer, get pinged in your own channel
          instead of the team's default channel above.
        </Text>
      </Flex>

      <Flex gap="2" wrap="wrap" align="end">
        <Flex direction="column" gap="1" className="min-w-0">
          <Text className="text-(--gray-11) text-[12px]">Channel</Text>
          <SlackChannelCombobox
            integrationId={integrationId}
            value={selectedChannelTarget}
            onChange={onChannelChange}
            offLabel="Off, don't notify me"
            ariaLabel="Notification channel"
            modal={channelComboboxModal}
            disabled={!integrationId}
          />
        </Flex>
        <Flex direction="column" gap="1" className="min-w-0">
          <Text className="text-(--gray-11) text-[12px]">Min. priority</Text>
          <SettingsOptionSelect
            value={minPriority ?? NOTIFY_ALL_VALUE}
            options={MIN_PRIORITY_OPTIONS}
            ariaLabel="Minimum priority to notify"
            disabled={!notificationsEnabled}
            className={SETTINGS_CONTROL_CLASS}
            onValueChange={onMinPriorityChange}
          />
        </Flex>
      </Flex>
    </Flex>
  );
}
