import {
  APP_LIFECYCLE_SERVICE,
  type IAppLifecycle,
} from "@posthog/platform/app-lifecycle";
import type {
  DeepLinkHandler,
  IDeepLinkRegistry,
} from "@posthog/platform/deep-link";
import { getDeeplinkProtocol } from "@posthog/shared";
import { inject, injectable } from "inversify";
import { isDevBuild } from "../../utils/env";
import {
  isAppImage,
  registerAppImageSchemes,
} from "../../utils/linux-appimage-protocol";
import { logger } from "../../utils/logger";

export type { DeepLinkHandler } from "@posthog/platform/deep-link";

const log = logger.scope("deep-link-service");

const LEGACY_PROTOCOLS = ["twig", "array"];

@injectable()
export class DeepLinkService implements IDeepLinkRegistry {
  private protocolRegistered = false;
  private handlers = new Map<string, DeepLinkHandler>();

  constructor(
    @inject(APP_LIFECYCLE_SERVICE)
    private readonly appLifecycle: IAppLifecycle,
  ) {}

  public registerProtocol(): void {
    if (this.protocolRegistered) {
      return;
    }

    // Dev uses `posthog-code-dev` so local builds do not steal `posthog-code`
    // from the production app. Production also registers legacy schemes.
    const schemes = [getDeeplinkProtocol(isDevBuild())];
    if (!isDevBuild()) {
      schemes.push(...LEGACY_PROTOCOLS);
    }

    for (const scheme of schemes) {
      this.appLifecycle.registerDeepLinkScheme(scheme);
    }

    // AppImage builds have no installed .desktop file, so the above
    // `setAsDefaultProtocolClient` calls (which point xdg at one) are no-ops and
    // the browser can't hand `posthog-code://callback?...` back after OAuth. Write
    // a desktop entry pointing at the stable $APPIMAGE path and register it.
    // Best-effort: failures here must not block startup.
    if (isAppImage()) {
      void registerAppImageSchemes(schemes);
    }

    this.protocolRegistered = true;
  }

  public registerHandler(key: string, handler: DeepLinkHandler): void {
    if (this.handlers.has(key)) {
      log.warn(`Overwriting existing handler for key: ${key}`);
    }
    this.handlers.set(key, handler);
  }

  public unregisterHandler(key: string): void {
    this.handlers.delete(key);
  }

  /**
   * Handle an incoming deep link URL
   *
   * NOTE: Strips the protocol and main key, passing only dynamic segments to handlers.
   * Supports the active primary scheme (posthog-code or posthog-code-dev) and,
   * in production only, legacy twig:// and array:// protocols.
   */
  public handleUrl(url: string): boolean {
    log.info("Received deep link:", url);

    const primary = getDeeplinkProtocol(isDevBuild());
    const isPrimaryProtocol = url.startsWith(`${primary}://`);
    const isLegacyProtocol =
      !isDevBuild() && LEGACY_PROTOCOLS.some((p) => url.startsWith(`${p}://`));

    if (!isPrimaryProtocol && !isLegacyProtocol) {
      log.warn("URL does not match protocol:", url);
      return false;
    }

    try {
      const parsedUrl = new URL(url);

      // The hostname is the main key (e.g., "task" in <scheme>://task/...)
      const mainKey = parsedUrl.hostname;

      if (!mainKey) {
        log.warn("Deep link has no main key:", url);
        return false;
      }

      const handler = this.handlers.get(mainKey);
      if (!handler) {
        log.warn("No handler registered for deep link key:", mainKey);
        return false;
      }

      // Extract path segments after the main key (strip leading slash)
      const pathSegments = parsedUrl.pathname.slice(1);

      log.info(
        `Routing deep link to '${mainKey}' handler with path: ${pathSegments || "(empty)"}`,
      );
      return handler(pathSegments, parsedUrl.searchParams);
    } catch (error) {
      log.error("Failed to parse deep link URL:", error);
      return false;
    }
  }

  public getProtocol(): string {
    return getDeeplinkProtocol(isDevBuild());
  }
}
