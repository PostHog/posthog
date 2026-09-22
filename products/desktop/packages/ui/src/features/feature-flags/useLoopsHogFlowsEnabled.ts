import { LOOPS_HOG_FLOWS_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/**
 * Whether the Loops screens are backed by workflows (`hog_flows`) instead of
 * the loops API. One hook so the list, detail, form and mutations flip
 * together; a mixed state would write to one backend and read from the other.
 */
export function useLoopsHogFlowsEnabled(): boolean {
  return useFeatureFlag(LOOPS_HOG_FLOWS_FLAG);
}
