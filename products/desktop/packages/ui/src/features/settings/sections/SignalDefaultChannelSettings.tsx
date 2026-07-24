import { useIsOrgAdmin } from "@posthog/ui/features/auth/useOrgRole";
import { useSignalSourceManager } from "@posthog/ui/features/inbox/hooks/useSignalSourceManager";
import { useIntegrationSelectors } from "@posthog/ui/features/integrations/store";
import { SlackChannelCombobox } from "@posthog/ui/features/settings/components/SlackChannelCombobox";
import { Box, Flex, Text } from "@radix-ui/themes";

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
      <Flex direction="column" gap="2" pt="2">
        <Flex direction="column" gap="1">
          <Box className="h-[14px] w-[200px] animate-pulse rounded bg-gray-4" />
          <Box className="h-[11px] w-[80%] animate-pulse rounded bg-gray-3" />
        </Flex>
        <Box className="mt-1 h-[28px] w-[200px] animate-pulse rounded bg-gray-3" />
      </Flex>
    );
  }

  // Connecting Slack is offered in the per-user section below; nothing to
  // configure here until a workspace exists.
  if (!hasSlackIntegration) return null;

  return (
    <Flex direction="column" gap="2" pt="2">
      <Flex direction="column" gap="1">
        <Text className="font-medium text-(--gray-12) text-sm">
          Default notification channel
        </Text>
        <Text className="text-(--gray-11) text-[13px]">
          Where every report is posted for the whole team. Reviewers who set
          their own channel below are notified there instead.
        </Text>
      </Flex>

      <Flex direction="column" gap="1" className="min-w-0">
        <Text className="text-(--gray-11) text-[12px]">Default Channel</Text>
        <SlackChannelCombobox
          integrationId={integrationId}
          value={channelTarget}
          onChange={(channel) => void handleUpdateTeamSlackChannel(channel)}
          offLabel="No default channel"
          ariaLabel="Default notification channel"
          modal={channelComboboxModal}
          disabled={!canEdit || !integrationId}
        />
      </Flex>

      {isAdmin === false ? (
        <Text className="text-(--gray-10) text-[11px]">
          Only organization admins can change the team's default channel.
        </Text>
      ) : null}
    </Flex>
  );
}
