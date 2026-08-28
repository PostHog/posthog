import { CHANNELS_LAYOUT_FLAG } from "@posthog/shared";
import { useBluebirdFlag } from "@posthog/ui/features/feature-flags/useBluebirdFlag";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/**
 * The single gate for the new channels layout — read this, not the raw flag.
 * No dev default, so dev matches prod; bluebird keeps its own backend guard.
 */
export function useChannelsLayout(): boolean {
  const bluebirdEnabled = useBluebirdFlag();
  const layoutEnabled = useFeatureFlag(
    CHANNELS_LAYOUT_FLAG,
    import.meta.env.DEV,
  );
  return layoutEnabled && bluebirdEnabled;
}
