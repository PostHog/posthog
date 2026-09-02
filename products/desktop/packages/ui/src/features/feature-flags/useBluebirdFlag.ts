import { PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

/**
 * The project-bluebird gate. Read this rather than the raw flag: the dev
 * default lives here once, so a surface can't ship with the flag on in dev and
 * off for a colleague (or the reverse) because a call site forgot it.
 *
 * Space-scoped surfaces want {@link useChannelsLayout} instead — that's this
 * flag *and* the channels layout, which is what actually puts a page inside a
 * space.
 */
export function useBluebirdFlag(): boolean {
  return useFeatureFlag(PROJECT_BLUEBIRD_FLAG, import.meta.env.DEV);
}
