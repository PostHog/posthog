import { browserTabsStore } from "@posthog/core/browser-tabs/browserTabsStore";
import { createSelectors } from "@posthog/ui/hooks/createSelectors";

const tabs = createSelectors(browserTabsStore);

/** Single store-selector: the live tab/window snapshot mirrored from main. */
export function useTabsSnapshot() {
  return tabs.use.snapshot();
}
