import { CANVASES_V2_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/**
 * The Canvases v2 gate. Read this rather than the raw flag, so every surface
 * answers the same for one person. `python manage.py sync_feature_flags`
 * creates the flag on a local instance.
 */
export function useCanvasesV2Flag(): boolean {
  return useFeatureFlag(CANVASES_V2_FLAG);
}
