import { CONTEXT_LAYER_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

export function useContextLayerFlag(): boolean {
  return useFeatureFlag(CONTEXT_LAYER_FLAG);
}
