import { getAuthIdentity } from "@posthog/core/auth/authIdentity";
import { useService } from "@posthog/di/react";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  BROWSER_TABS_CLIENT,
  type BrowserTabsClient,
} from "@posthog/ui/features/browser-tabs/browserTabsClient";
import { openOnboardingTab } from "@posthog/ui/shell/onboardingTab";
import { useCallback } from "react";

export function useOpenOnboardingTab(): () => void {
  const tabsClient = useService<BrowserTabsClient>(BROWSER_TABS_CLIENT);
  const authIdentity = useAuthStateValue(getAuthIdentity);
  return useCallback(() => {
    void openOnboardingTab(authIdentity, tabsClient);
  }, [authIdentity, tabsClient]);
}
