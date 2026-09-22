import { CHANNEL_REPORTS_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/**
 * Whether spaces own reports (sidebar tab, feed cards, in-space detail) and the
 * inbox is retired as a destination. One hook so every surface flips together.
 * Defaults on in dev builds, same as loops and bluebird.
 */
export function useChannelReportsEnabled(): boolean {
  return useFeatureFlag(CHANNEL_REPORTS_FLAG, import.meta.env.DEV);
}
