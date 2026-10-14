import { CHANNELS_LAYOUT_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/**
 * The single gate for the new channels layout — read this, not the raw flag.
 * No dev default, so dev matches prod.
 */
export function useChannelsLayout(): boolean {
  return useFeatureFlag(CHANNELS_LAYOUT_FLAG, import.meta.env.DEV);
}
