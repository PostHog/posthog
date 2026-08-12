import { DESKTOP_SUPPORT_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

export function useSupportFlag(): boolean {
  return useFeatureFlag(DESKTOP_SUPPORT_FLAG, import.meta.env.DEV);
}
