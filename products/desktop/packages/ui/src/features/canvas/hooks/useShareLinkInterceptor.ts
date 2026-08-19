import { interceptShareLinkClicks } from "@posthog/ui/utils/shareLinks";
import { useEffect } from "react";

/**
 * App-wide fallback so a canvas or channel link opens in the app rather than the
 * browser, whichever surface rendered it. See {@link interceptShareLinkClicks}.
 */
export function useShareLinkInterceptor(): void {
  useEffect(() => interceptShareLinkClicks(document), []);
}
