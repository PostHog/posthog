import { useIsOrgAdmin } from "@posthog/ui/features/auth/useOrgRole";
import { useSignalSourceManager } from "@posthog/ui/features/inbox/hooks/useSignalSourceManager";
import { useIntegrationSelectors } from "@posthog/ui/features/integrations/store";
import { SettingsCardRow } from "@posthog/ui/features/settings/components/SettingsCard";
import { SlackChannelCombobox } from "@posthog/ui/features/settings/components/SlackChannelCombobox";

interface SignalDefaultChannelSettingsProps {
  /** Workspace whose channels are listed — shared with the per-user section. */
  integrationId: number | null;
  channelComboboxModal?: boolean;
  isLoading?: boolean;
}

export function SignalDefaultChannelSettings({
  integrationId,
  channelComboboxModal = false,
  isLoading = false,
}: SignalDefaultChannelSettingsProps) {
  const { hasSlackIntegration } = useIntegrationSelectors();
  const { teamConfig, handleUpdateTeamSlackChannel } = useSignalSourceManager();
  const { isAdmin } = useIsOrgAdmin();

  const channelTarget = teamConfig?.default_slack_notification_channel ?? null;
  const canEdit = isAdmin === true;

  if (isLoading) {
    return (
      <div className="flex min-h-11 items-center justify-between gap-6 px-3.5 py-2">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="h-[13px] w-[200px] animate-pulse rounded bg-gray-4" />
          <div className="h-[11px] w-[280px] animate-pulse rounded bg-gray-3" />
        </div>
        <div className="h-[28px] w-[200px] shrink-0 animate-pulse rounded bg-gray-3" />
      </div>
    );
  }

  // Connecting Slack is offered by the workspace section; nothing to configure
  // here until a workspace exists.
  if (!hasSlackIntegration) return null;

  return (
    <SettingsCardRow
      label="Default notification channel"
      description={
        isAdmin === false
          ? "Where every report is posted for the whole team; only organization admins can change it"
          : "Where every report is posted for the whole team; reviewers who set their own channel are notified there instead"
      }
    >
      <SlackChannelCombobox
        integrationId={integrationId}
        value={channelTarget}
        onChange={(channel) => void handleUpdateTeamSlackChannel(channel)}
        offLabel="No default channel"
        ariaLabel="Default notification channel"
        modal={channelComboboxModal}
        disabled={!canEdit || !integrationId}
      />
    </SettingsCardRow>
  );
}
