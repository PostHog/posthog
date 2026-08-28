import type { SlackChannelOption } from "@posthog/shared/domain-types";

export interface SlackIntegrationLike {
  id: number;
  display_name?: string;
  config?: { account?: { name?: string } };
}

export function buildChannelTargetValue(
  channelId: string,
  channelName: string,
): string {
  const display = channelName.startsWith("#") ? channelName : `#${channelName}`;
  return `${channelId}|${display}`;
}

export function parseChannelIdFromTargetValue(
  value: string | null | undefined,
): string | null {
  if (!value) return null;
  return value.split("|")[0]?.trim() || null;
}

export function parseChannelNameFromTargetValue(
  value: string | null | undefined,
): string | null {
  if (!value) return null;
  const display = value.split("|")[1]?.trim();
  if (!display) return null;
  return display.startsWith("#") ? display.slice(1) : display;
}

export function getSlackIntegrationLabel(
  integration: SlackIntegrationLike,
): string {
  return (
    integration.display_name ??
    integration.config?.account?.name ??
    `Slack workspace ${integration.id}`
  );
}

export function configuredSlackChannelOption(
  id: string,
  name: string,
): SlackChannelOption {
  return {
    id,
    name,
    is_private: false,
    is_member: true,
    is_ext_shared: false,
    is_private_without_access: false,
  };
}

export function deriveEffectiveIntegrationId(
  selectedId: number | null,
  integrations: readonly SlackIntegrationLike[],
): number | null {
  return selectedId ?? (integrations.length === 1 ? integrations[0].id : null);
}

export function mergeVisibleChannels(
  fetched: readonly SlackChannelOption[],
  selectedChannelId: string | null,
  selectedChannelName: string | null,
): SlackChannelOption[] {
  const channels = [...fetched];
  if (
    selectedChannelId &&
    selectedChannelName &&
    !channels.some((channel) => channel.id === selectedChannelId)
  ) {
    channels.unshift(
      configuredSlackChannelOption(selectedChannelId, selectedChannelName),
    );
  }
  return channels;
}
