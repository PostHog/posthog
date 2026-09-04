import { TrashIcon } from "@phosphor-icons/react";
import type { ScoutSlackDestination } from "@posthog/api-client/posthog-client";
import {
  deriveSlackTargetMode,
  MAX_SCOUT_SLACK_DM_TARGETS,
  type SlackTargetMode,
} from "@posthog/core/scouts/scoutSlackDestination";
import { getSlackIntegrationLabel } from "@posthog/core/settings/slackNotificationTarget";
import {
  Button,
  Switch as QuillSwitch,
  Text as QuillText,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { useIntegrationSelectors } from "@posthog/ui/features/integrations/store";
import { useIntegrations } from "@posthog/ui/features/integrations/useIntegrations";
import { SlackChannelCombobox } from "@posthog/ui/features/settings/components/SlackChannelCombobox";
import { SlackMemberPicker } from "@posthog/ui/features/settings/components/SlackMemberPicker";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { useState } from "react";

interface ScoutSlackDestinationSettingsProps {
  destination?: ScoutSlackDestination | null;
  disabled?: boolean;
  /** Emits the next Slack destination, or null to turn Slack delivery off. */
  onChange: (slack: ScoutSlackDestination | null) => void;
}

const MODE_OPTIONS = [
  { value: "channel", label: "Channel" },
  { value: "dm", label: "Direct message" },
];

export function ScoutSlackDestinationSettings({
  destination,
  disabled = false,
  onChange,
}: ScoutSlackDestinationSettingsProps) {
  const { isPending: integrationsLoading } = useIntegrations();
  const { slackIntegrations, hasSlackIntegration } = useIntegrationSelectors();
  const integrations = slackIntegrations;

  const configuredIntegration = destination
    ? integrations.find(
        (integration) => integration.id === destination.integration_id,
      )
    : undefined;
  const selectedIntegration =
    configuredIntegration ??
    (integrations.length === 1 ? integrations[0] : null);

  const hasChannel = Boolean(destination?.channel);
  const hasUsers = Boolean(destination?.users?.length);
  const hasTarget = hasChannel || hasUsers;

  // The toggle is view state only: switching it must never write, or an
  // exploratory click would wipe a live destination. The saved target changes
  // only when a new target is picked.
  const [pendingMode, setPendingMode] = useState<SlackTargetMode | null>(null);
  const mode: SlackTargetMode =
    pendingMode ?? deriveSlackTargetMode(destination);

  const selectWorkspace = (integrationId: number) => {
    setPendingMode(mode);
    onChange({ integration_id: integrationId, channel: null });
  };

  const selectChannel = (channel: string | null) => {
    if (!channel || !selectedIntegration) {
      // An empty picker still emits clears; only clear when this mode's target
      // is actually saved, so viewing the other mode never wipes a live target.
      if (hasChannel) onChange(null);
      return;
    }
    onChange({
      integration_id: selectedIntegration.id,
      channel,
      thread_reports: destination?.thread_reports ?? false,
    });
  };

  const selectMembers = (users: string[]) => {
    if (!selectedIntegration) return;
    if (!users.length) {
      if (!hasUsers) return;
      // Removing the last recipient empties the target; pin the mode so the
      // toggle does not fall back to its channel default mid-edit.
      setPendingMode("dm");
      onChange({ integration_id: selectedIntegration.id, channel: null });
      return;
    }
    onChange({
      integration_id: selectedIntegration.id,
      users: users.slice(0, MAX_SCOUT_SLACK_DM_TARGETS),
    });
  };

  const setThreadReports = (threadReports: boolean) => {
    // Thread only against the stored destination's own workspace; pairing the
    // saved channel with a fallback workspace would break delivery.
    if (!configuredIntegration || !destination?.channel) return;
    onChange({
      integration_id: configuredIntegration.id,
      channel: destination.channel,
      thread_reports: threadReports,
    });
  };

  const disableSlack = () => {
    setPendingMode(mode);
    onChange(null);
  };

  return (
    <div className="flex flex-col gap-2 border-(--gray-4) border-t pt-3">
      <div className="flex min-w-0 flex-col">
        <QuillText size="xs" className="text-gray-12">
          Slack delivery
        </QuillText>
        <QuillText size="xxs" className="text-gray-10">
          Post each run's output to a channel, or send it as a direct message
        </QuillText>
      </div>
      {integrationsLoading && slackIntegrations.length === 0 ? (
        <QuillText size="xxs" className="text-gray-10">
          Loading Slack workspaces…
        </QuillText>
      ) : !hasSlackIntegration ? (
        <QuillText size="xxs" className="text-gray-10">
          Connect a Slack workspace in settings to deliver this scout's output.
        </QuillText>
      ) : (
        <div className="flex max-w-md flex-col gap-2">
          {integrations.length > 1 ? (
            <SettingsOptionSelect
              value={selectedIntegration ? String(selectedIntegration.id) : ""}
              options={integrations.map((integration) => ({
                value: String(integration.id),
                label: getSlackIntegrationLabel(integration),
              }))}
              ariaLabel="Slack workspace"
              placeholder="Select workspace"
              disabled={disabled}
              onValueChange={(value) => selectWorkspace(Number(value))}
            />
          ) : null}
          {selectedIntegration ? (
            <>
              <SettingsOptionSelect
                value={mode}
                options={MODE_OPTIONS}
                ariaLabel="Slack delivery target"
                disabled={disabled}
                onValueChange={(value) =>
                  setPendingMode(value as SlackTargetMode)
                }
              />
              <div className="flex items-center gap-2">
                <div className="min-w-0 flex-1">
                  {mode === "channel" ? (
                    <SlackChannelCombobox
                      integrationId={selectedIntegration.id}
                      value={
                        configuredIntegration
                          ? (destination?.channel ?? null)
                          : null
                      }
                      onChange={selectChannel}
                      ariaLabel="Slack channel"
                      disabled={disabled}
                    />
                  ) : (
                    <SlackMemberPicker
                      integrationId={selectedIntegration.id}
                      value={
                        configuredIntegration ? (destination?.users ?? []) : []
                      }
                      onChange={selectMembers}
                      max={MAX_SCOUT_SLACK_DM_TARGETS}
                      ariaLabel="Slack members"
                      disabled={disabled}
                    />
                  )}
                </div>
                {hasTarget ? (
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <span className="inline-flex">
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={disabled}
                            aria-label="Turn off Slack delivery"
                            onClick={disableSlack}
                          >
                            <TrashIcon size={14} />
                          </Button>
                        </span>
                      }
                    />
                    <TooltipContent>
                      Turn off Slack delivery for this scout
                    </TooltipContent>
                  </Tooltip>
                ) : null}
              </div>
              {mode === "channel" ? (
                <>
                  <QuillText size="xxs" className="text-gray-10">
                    {hasUsers
                      ? "Direct messages stay on until you pick a channel to replace them. PostHog must be in the channel. Invite it with "
                      : "PostHog must be in the channel. Invite it with "}
                    <code>/invite @PostHog</code>.
                  </QuillText>
                  {configuredIntegration && hasChannel ? (
                    <div className="flex items-center justify-between gap-4">
                      <QuillText size="xxs" className="text-gray-12">
                        Post reports as a thread
                      </QuillText>
                      <QuillSwitch
                        size="sm"
                        checked={destination?.thread_reports ?? false}
                        disabled={disabled}
                        onCheckedChange={setThreadReports}
                        aria-label="Post reports as a thread"
                      />
                    </div>
                  ) : null}
                </>
              ) : (
                <QuillText size="xxs" className="text-gray-10">
                  {hasChannel
                    ? `The channel stays on until you pick up to ${MAX_SCOUT_SLACK_DM_TARGETS} people to replace it. Each person gets their own direct message from the PostHog app.`
                    : `Each person gets their own direct message from the PostHog app (up to ${MAX_SCOUT_SLACK_DM_TARGETS} people).`}
                </QuillText>
              )}
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}
