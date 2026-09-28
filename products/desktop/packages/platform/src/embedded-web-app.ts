/**
 * Where the host finds the PostHog web app's embed bundle, the module the Library pane mounts
 * (`mountLegacyApp` from `frontend/src/embed` in the monorepo).
 */
export interface EmbeddedWebAppConfig {
  /** Absolute URL of the embed module. */
  moduleUrl: string;
  /** The web app's own analytics project, so its feature flags resolve. Absent leaves them off. */
  analytics?: { apiKey: string; apiHost: string };
}

export interface IEmbeddedWebAppSource {
  /**
   * The bundle to load, or null when this host cannot load one. Library then offers to open
   * PostHog in the browser instead. The bundle talks to whichever region the session belongs to.
   */
  getConfig(): EmbeddedWebAppConfig | null;
}

export const EMBEDDED_WEB_APP_SOURCE = Symbol.for(
  "posthog.platform.embeddedWebAppSource",
);
