import { useChannelReportsEnabled } from "@posthog/ui/features/feature-flags/useChannelReportsEnabled";
import { useReportsInboxEnabled } from "@posthog/ui/features/feature-flags/useReportsInboxEnabled";

export function isInboxAvailable(
  channelReportsEnabled: boolean,
  reportsInboxEnabled: boolean,
): boolean {
  return !channelReportsEnabled || reportsInboxEnabled;
}

export function useInboxAvailable(): boolean {
  return isInboxAvailable(useChannelReportsEnabled(), useReportsInboxEnabled());
}
