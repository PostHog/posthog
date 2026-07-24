import { AUTORESEARCH_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "../feature-flags/useFeatureFlag";

/**
 * Whether autoresearch is available: staff-gated via feature flag in
 * production, always on in dev builds.
 */
export function useAutoresearchEnabled(): boolean {
  return useFeatureFlag(AUTORESEARCH_FLAG) || import.meta.env.DEV;
}
