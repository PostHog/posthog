import { COMMENTS_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

export function useCommentsEnabled(): boolean {
  return useFeatureFlag(COMMENTS_FLAG);
}
