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
 * or channel). The root layout uses this to render the new-tab placeholder on
 * the `/spaces` index instead of the space list (`showBlankTab` in `__root`).
 */
export function useActiveTabIsBlank(): boolean {
  return activeTabIsBlank(useTabsSnapshot());
}

/**
 * True when the primary window has no tabs at all — the user closed every tab.
 */
export function usePrimaryWindowHasNoTabs(): boolean {
  return primaryWindowHasNoTabs(useTabsSnapshot());
}
