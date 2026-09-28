import type {
  EmbeddedWebAppConfig,
  IEmbeddedWebAppSource,
} from "@posthog/platform/embedded-web-app";

/**
 * Reads the embed bundle location from the build environment. `VITE_EMBEDDED_WEB_APP_URL` points at
 * the web app's `embed.js`. When it is unset, Library offers to open PostHog in the browser.
 */
export class WebEmbeddedWebAppSource implements IEmbeddedWebAppSource {
  getConfig(): EmbeddedWebAppConfig | null {
    const moduleUrl: string | undefined = import.meta.env
      .VITE_EMBEDDED_WEB_APP_URL;
    if (!moduleUrl) return null;
    const apiKey: string | undefined = import.meta.env
      .VITE_EMBEDDED_WEB_APP_ANALYTICS_KEY;
    const apiHost: string | undefined = import.meta.env
      .VITE_EMBEDDED_WEB_APP_ANALYTICS_HOST;
    return {
      moduleUrl,
      analytics: apiKey && apiHost ? { apiKey, apiHost } : undefined,
    };
  }
}
