export type AnalyticsProperties = Record<string, string | number | boolean>;

export interface IAnalytics {
  initialize(): void;
  track(eventName: string, properties?: AnalyticsProperties): void;
  identify(userId: string, properties?: AnalyticsProperties): void;
  setCurrentUserId(userId: string | null): void;
  getCurrentUserId(): string | null;
  /** Host-owned analytics session id, minted lazily on first request. */
  getOrCreateSessionId(): string;
  /**
   * Renderer's live posthog-js session id, pushed whenever it changes (or null
   * while stitching is off). The Electron main process uses it to decorate
   * outbound PostHog web links so both surfaces record under one session;
   * hosts without a separate main process no-op.
   */
  setRendererSessionId(sessionId: string | null): void;
  resetUser(): void;
  captureException(
    error: unknown,
    additionalProperties?: Record<string, unknown>,
  ): void;
  flush(): Promise<void>;
  shutdown(): Promise<void>;
}

export const ANALYTICS_SERVICE = Symbol.for("posthog.platform.analytics");
