import { DESKTOP_SUPPORT_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/**
 * The Support gate. Read this rather than the raw flag so the dev default lives
 * in one place: the nav item, the routes and the ticket commands must agree, or
 * a build ships a destination that leads nowhere.
 */
export function useSupportFlag(): boolean {
  return useFeatureFlag(DESKTOP_SUPPORT_FLAG, import.meta.env.DEV);
}
