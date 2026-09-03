import { REPORTS_INBOX_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/**
 * Whether the global reports inbox owns the inbox nav slot. One hook so the
 * page takeover and the nav entries flip together. Defaults on in dev builds,
 * same as channel reports.
 */
export function useReportsInboxEnabled(): boolean {
  return useFeatureFlag(REPORTS_INBOX_FLAG, import.meta.env.DEV);
}
