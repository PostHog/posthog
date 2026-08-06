import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { getDeeplinkProtocol, isPostHogCodeDeeplink } from "@posthog/shared";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";

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
export function openAnnouncementCta(url: string): "deeplink" | "external" {
  if (isPostHogCodeDeeplink(url)) {
    void resolveService<HostTrpcClient>(HOST_TRPC_CLIENT).deepLink.open.mutate({
      url: toActiveScheme(url),
    });
    return "deeplink";
  }
  openExternalUrl(url);
  return "external";
}
