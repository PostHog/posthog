import { TRIAGE_FOCUS_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/**
 * On by default in dev builds so focus mode can be iterated on locally;
 * production stays flag-gated until it stabilizes.
 */
export function useTriageFocusEnabled(): boolean {
  return useFeatureFlag(TRIAGE_FOCUS_FLAG, import.meta.env.DEV);
}
