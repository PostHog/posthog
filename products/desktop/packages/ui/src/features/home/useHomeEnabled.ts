import { HOME_FLAG } from "@posthog/shared";
import { useBluebirdFlag } from "@posthog/ui/features/feature-flags/useBluebirdFlag";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/**
 * The single gate for Home — read this, not the raw flag. Home lives in the
 * spaces chrome and its suggestions create spaces, so bluebird gates it too.
 */
export function useHomeEnabled(): boolean {
  const bluebirdEnabled = useBluebirdFlag();
  const homeEnabled = useFeatureFlag(HOME_FLAG, import.meta.env.DEV);
  return homeEnabled && bluebirdEnabled;
}
