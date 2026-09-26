import { CANVAS_COMMENTS_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

export function useCanvasCommentsEnabled(
  commentTaskId: string | null,
): boolean {
  return useFeatureFlag(CANVAS_COMMENTS_FLAG) || !!commentTaskId;
}
