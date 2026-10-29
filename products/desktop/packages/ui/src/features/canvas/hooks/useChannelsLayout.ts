import { CHANNELS_LAYOUT_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/**
 * The single gate for the new channels layout — read this, not the raw flag.
 * Dev builds default it on unless the dev kill switch forces it off (see
 * devFlagOverrides).
 */
export function useChannelsLayout(): boolean {
  return useFeatureFlag(CHANNELS_LAYOUT_FLAG, import.meta.env.DEV);
}
