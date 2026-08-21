import { SELF_DRIVING_HOME_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/**
 * Whether the decision-ordered Self-Driving home replaces the inbox's pipeline
 * tabs and reclaims the inbox nav slot. One hook so the page takeover and the
 * nav entries flip together. Defaults on in dev builds, same as channel reports.
 */
export function useSelfDrivingHomeEnabled(): boolean {
  return useFeatureFlag(SELF_DRIVING_HOME_FLAG, import.meta.env.DEV);
}
