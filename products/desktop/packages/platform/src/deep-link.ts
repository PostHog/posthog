export type DeepLinkHandler = (
  path: string,
  searchParams: URLSearchParams,
) => boolean;

export interface IDeepLinkRegistry {
  registerHandler(key: string, handler: DeepLinkHandler): void;
  unregisterHandler(key: string): void;
  getProtocol(): string;
}

export const DEEP_LINK_SERVICE = Symbol.for("posthog.platform.deepLink");
