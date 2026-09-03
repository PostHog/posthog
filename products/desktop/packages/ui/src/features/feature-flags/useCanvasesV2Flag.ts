import { CANVASES_V2_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/**
 * The Canvases v2 gate. Read this rather than the raw flag, so the dev default
 * lives in one place and no surface ships with the flag on for one person and
 * off for the next.
 */
export function useCanvasesV2Flag(): boolean {
  return useFeatureFlag(CANVASES_V2_FLAG, import.meta.env.DEV);
}
