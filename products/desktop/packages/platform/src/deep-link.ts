export type DeepLinkHandler = (
  path: string,
  searchParams: URLSearchParams,
) => boolean;

export interface IDeepLinkRegistry {
  registerHandler(key: string, handler: DeepLinkHandler): void;
  unregisterHandler(key: string): void;
  getProtocol(): string;
  /**
   * Dispatch a deep-link URL through the registered handlers — the same path
   * OS-delivered links take, callable from in-app surfaces without an OS hop.
   * Lives on the platform interface because host-router forwards to it
   * (deepLink.open) and cannot import the host's own service token.
   */
  handleUrl(url: string): boolean;
}

export const DEEP_LINK_SERVICE = Symbol.for("posthog.platform.deepLink");
