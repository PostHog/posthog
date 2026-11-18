import { DESKTOP_WORK_LAYOUT_FLAG } from "@posthog/shared";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

export function useWorkLayout(): boolean {
  const channelsLayout = useChannelsLayout();
  const enabled = useFeatureFlag(DESKTOP_WORK_LAYOUT_FLAG, import.meta.env.DEV);
  return channelsLayout && enabled;
}
