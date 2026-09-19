import { DESKTOP_WORK_LAYOUT_FLAG } from "@posthog/shared";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/**
 * The single gate for the Work layout. Builds on the spaces layout: without
 * that chrome there is no rail or column to reshape. Dev defaults on so the
 * redesign is what a dev build shows; `ph-dev-flags-off` turns it back off.
 */
export function useWorkLayout(): boolean {
  const channelsLayout = useChannelsLayout();
  const enabled = useFeatureFlag(DESKTOP_WORK_LAYOUT_FLAG, import.meta.env.DEV);
  return channelsLayout && enabled;
}
