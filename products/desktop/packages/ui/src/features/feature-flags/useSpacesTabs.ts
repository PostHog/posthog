import { SPACES_TABS_FLAG } from "@posthog/shared";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/**
 * Whether the tab strip is shown inside the spaces layout. Read this rather
 * than the raw flag, so the spaces-layout requirement lives in one place.
 *
 * Only the strip is gated. The per-tab model underneath it is unconditional:
 * with the strip hidden the window simply holds one tab, which behaves the way
 * the window-global state did before it.
 */
export function useSpacesTabs(): boolean {
  const spacesLayout = useChannelsLayout();
  const enabled = useFeatureFlag(SPACES_TABS_FLAG, import.meta.env.DEV);
  return spacesLayout && enabled;
}
