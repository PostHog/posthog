import { browserTabsStore } from "@posthog/core/browser-tabs/browserTabsStore";
import { activeTabIsBlank, primaryWindowHasNoTabs } from "@posthog/shared";
import { createSelectors } from "@posthog/ui/hooks/createSelectors";

const tabs = createSelectors(browserTabsStore);

/** Single store-selector: the live tab/window snapshot mirrored from main. */
export function useTabsSnapshot() {
  return tabs.use.snapshot();
}

/**
 * True when the primary window's active tab is a blank "+" tab (no canvas, task,
 * or channel). The blank tab parks at `/website`, whose index would otherwise
 * redirect to the first channel — callers use this to suppress that redirect so
 * a blank tab (and the in-flight navigation leaving it) isn't hijacked.
 */
export function useActiveTabIsBlank(): boolean {
  return activeTabIsBlank(useTabsSnapshot());
}

/**
 * True when the primary window has no tabs at all — the user closed every tab.
 * The /website index renders the new-tab screen for this state rather than
 * redirecting to the first channel (which would silently re-open a tab).
 */
export function usePrimaryWindowHasNoTabs(): boolean {
  return primaryWindowHasNoTabs(useTabsSnapshot());
}
