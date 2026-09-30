import { SIGNALS_PERSONAL_INBOX_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/** Whether For you reads the server's personal inbox (`scope=for_me`) and offers relevance order. */
export function usePersonalInboxEnabled(): boolean {
  return useFeatureFlag(SIGNALS_PERSONAL_INBOX_FLAG);
}
