import { useHostTRPCClient } from "@posthog/host-router/react";
import { getDeeplinkProtocol, isPostHogCodeDeeplink } from "@posthog/shared";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useCallback } from "react";

// Payloads are authored with the production scheme; dev builds register
// posthog-code-dev://, and the dispatcher only accepts the active one.
function toActiveScheme(url: string): string {
  return url.replace(
    /^posthog-code(-dev)?:\/\//,
    `${getDeeplinkProtocol(import.meta.env.DEV)}://`,
  );
}

/**
 * Routes a CTA url: posthog-code:// deep links dispatch in-app through the
 * main-process handler (no OS hop, no browser), https opens the browser.
 */
export function useOpenAnnouncementCta(): (
  url: string,
) => "deeplink" | "external" {
  const client = useHostTRPCClient();
  return useCallback(
    (url: string) => {
      if (isPostHogCodeDeeplink(url)) {
        void client.deepLink.open.mutate({ url: toActiveScheme(url) });
        return "deeplink";
      }
      openExternalUrl(url);
      return "external";
    },
    [client],
  );
}
