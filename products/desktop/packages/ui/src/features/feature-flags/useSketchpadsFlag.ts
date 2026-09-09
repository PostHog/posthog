import { SKETCHPADS_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

export function useSketchpadsFlag(): boolean {
  return useFeatureFlag(SKETCHPADS_FLAG);
}
