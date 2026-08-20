import { CONTEXT_LAYER_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/**
 * The context-wiki gate. Read this rather than the raw flag: the dev default
 * lives here once, so the nav entries and the explorer can't disagree about
 * whether the wiki exists because a call site forgot the fallback.
 */
export function useContextLayerFlag(): boolean {
  return useFeatureFlag(CONTEXT_LAYER_FLAG, import.meta.env.DEV);
}
