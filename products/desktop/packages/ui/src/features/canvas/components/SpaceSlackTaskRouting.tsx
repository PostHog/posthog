import { SlackLogoIcon } from "@phosphor-icons/react";
import {
  buildChannelTargetValue,
  parseChannelIdFromTargetValue,
  parseChannelNameFromTargetValue,
} from "@posthog/core/settings/slackNotificationTarget";
import { Button, Spinner } from "@posthog/quill";
import type { TaskChannel } from "@posthog/shared/domain-types";
import { useUpdateTaskChannelSlackTaskRouting } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useIntegrations } from "@posthog/ui/features/integrations/useIntegrations";
import { SlackWorkspaceChannelPicker } from "@posthog/ui/features/settings/components/SlackWorkspaceChannelPicker";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useState } from "react";

interface SpaceSlackTaskRoutingProps {
  channel: TaskChannel;
}

export function SpaceSlackTaskRouting({ channel }: SpaceSlackTaskRoutingProps) {
  const integrationsQuery = useIntegrations();
  const update = useUpdateTaskChannelSlackTaskRouting();
  const [selectedIntegrationId, setSelectedIntegrationId] = useState<
    number | null
  >(null);

  if (channel.channel_type !== "public") return null;

  const slackIntegrations = (integrationsQuery.data ?? []).filter(
    (integration) => integration.kind === "slack",
  );
  const slackTaskRouting = channel.slack_task_routing ?? null;
  const integrationId =
    selectedIntegrationId ??
    slackTaskRouting?.integration ??
    slackIntegrations[0]?.id ??
    null;
  const channelValue =
    slackTaskRouting && slackTaskRouting.integration === integrationId
      ? buildChannelTargetValue(
          slackTaskRouting.slack_channel_id,
          slackTaskRouting.display_name ?? slackTaskRouting.slack_channel_id,
        )
      : null;
  const selectedChannelLabel = slackTaskRouting
    ? `#${slackTaskRouting.display_name ?? slackTaskRouting.slack_channel_id}`
    : "No Slack channel";

  const updateRouting = (channelTarget: string | null): void => {
    if (channelTarget === null) {
      update.mutate({ channelId: channel.id, slackTaskRouting: null });
      return;
    }

    const slackChannelId = parseChannelIdFromTargetValue(channelTarget);
    const displayName = parseChannelNameFromTargetValue(channelTarget);
    if (!slackChannelId || integrationId === null) return;

    update.mutate({
      channelId: channel.id,
      slackTaskRouting: {
        integration: integrationId,
        slack_channel_id: slackChannelId,
        display_name: displayName,
      },
    });
  };

  return (
    <div className="flex shrink-0 flex-col gap-2 border-b border-b-(--gray-5) px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <SlackLogoIcon size={15} className="text-muted-foreground" />
        <span className="font-medium text-[13px]">Slack task channel</span>
        {update.isPending ? <Spinner className="size-3" /> : null}
        {update.error ? (
          <span className="text-[12px] text-red-11">
            Couldn&apos;t save the Slack channel. Try again.
          </span>
        ) : null}
      </div>
      {integrationsQuery.isPending ? (
        <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
          <span>{selectedChannelLabel}</span>
          <Spinner className="size-3" />
          <span>Loading Slack connections.</span>
        </div>
      ) : integrationsQuery.isError ? (
        <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
          <span>{selectedChannelLabel}</span>
          <span>Couldn&apos;t load Slack connections.</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void integrationsQuery.refetch()}
          >
            Retry
          </Button>
        </div>
      ) : slackIntegrations.length === 0 ? (
        <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
          <span>{selectedChannelLabel}</span>
          <span>Connect Slack in Settings to route new Slack tasks here.</span>
          <Button
            variant="outline"
            size="sm"
            data-attr="space-slack-routing-settings"
            onClick={() => openSettings("slack")}
          >
            Open Slack settings
          </Button>
        </div>
      ) : (
        <SlackWorkspaceChannelPicker
          integrations={slackIntegrations}
          integrationId={integrationId}
          channelValue={channelValue}
          channelAriaLabel="Slack task channel"
          offLabel="No Slack channel"
          publicOnly
          disabled={update.isPending}
          onIntegrationChange={setSelectedIntegrationId}
          onChannelChange={updateRouting}
        />
      )}
    </div>
  );
}
