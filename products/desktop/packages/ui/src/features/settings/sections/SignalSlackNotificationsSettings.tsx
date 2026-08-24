import type { SignalReportPriority } from "@posthog/shared/domain-types";
import { useSignalSourceManager } from "@posthog/ui/features/inbox/hooks/useSignalSourceManager";
import { useIntegrationSelectors } from "@posthog/ui/features/integrations/store";
import { SettingsCardRow } from "@posthog/ui/features/settings/components/SettingsCard";
import { SlackChannelCombobox } from "@posthog/ui/features/settings/components/SlackChannelCombobox";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";

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

interface SignalSlackNotificationsSettingsProps {
  /** Workspace whose channels are listed — shared with the team default. */
  integrationId: number | null;
  channelComboboxModal?: boolean;
  isLoading?: boolean;
}

export function SignalSlackNotificationsSettings({
  integrationId,
  channelComboboxModal = false,
  isLoading = false,
}: SignalSlackNotificationsSettingsProps) {
  const { hasSlackIntegration } = useIntegrationSelectors();
  const { userAutonomyConfig, handleUpdateSlackNotifications } =
    useSignalSourceManager();

  const selectedChannelTarget =
    userAutonomyConfig?.slack_notification_channel ?? null;
  const minPriority =
    userAutonomyConfig?.slack_notification_min_priority ?? null;

  const notificationsEnabled = !!integrationId && !!selectedChannelTarget;

  if (isLoading) {
    return (
      <div className="flex min-h-11 items-center justify-between gap-6 px-3.5 py-2">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="h-[13px] w-[160px] animate-pulse rounded bg-gray-4" />
          <div className="h-[11px] w-[280px] animate-pulse rounded bg-gray-3" />
        </div>
        <div className="h-[28px] w-[200px] shrink-0 animate-pulse rounded bg-gray-3" />
      </div>
    );
  }

  // Connecting Slack is offered by the workspace section; nothing to configure
  // here until a workspace exists.
  if (!hasSlackIntegration) return null;

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
    <>
      <SettingsCardRow
        label="Notify me directly"
        description="When you're a suggested reviewer, get pinged in your own channel instead of the team's default channel."
      >
        <SlackChannelCombobox
          integrationId={integrationId}
          value={selectedChannelTarget}
          onChange={onChannelChange}
          offLabel="Off, don't notify me"
          ariaLabel="Notification channel"
          modal={channelComboboxModal}
          disabled={!integrationId}
        />
      </SettingsCardRow>
      <SettingsCardRow
        label="Minimum priority"
        description="Only ping me for reports at or above this priority."
      >
        <SettingsOptionSelect
          value={minPriority ?? NOTIFY_ALL_VALUE}
          options={MIN_PRIORITY_OPTIONS}
          ariaLabel="Minimum priority to notify"
          disabled={!notificationsEnabled}
          className="min-w-[200px] max-w-[240px]"
          onValueChange={onMinPriorityChange}
        />
      </SettingsCardRow>
    </>
  );
}
