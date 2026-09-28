import { DESKTOP_TODAY_ASK_LIBRARY_FLAG } from "@posthog/shared";
import { useWorkLayout } from "@posthog/ui/features/canvas/hooks/useWorkLayout";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/** The rail shows Today, Ask and Library. Ask is the work layout, so it needs that layout too. */
export function useTodayAskLibraryLayout(): boolean {
  const workLayout = useWorkLayout();
  const enabled = useFeatureFlag(DESKTOP_TODAY_ASK_LIBRARY_FLAG);
  return workLayout && enabled;
}
