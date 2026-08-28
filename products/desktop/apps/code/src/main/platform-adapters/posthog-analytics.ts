import type {
  AnalyticsProperties,
  IAnalytics,
} from "@posthog/platform/analytics";
import { PostHog } from "posthog-node";
import { getAppVersion } from "../utils/env";
import { uuidv7 } from "../utils/uuidv7";

export class PosthogNodeAnalytics implements IAnalytics {
  private client: PostHog | null = null;
  private currentUserId: string | null = null;
  private sessionId: string | null = null;
  // Kept separate from the boot-time sessionId above: the renderer's posthog-js
  // session rotates on idle and logout, while the boot id stays fixed for the
  // process lifetime and keeps seeding the renderer via preload argv.
  private rendererSessionId: string | null = null;

  initialize(): void {
    if (this.client) {
      return;
    }

    const apiKey = process.env.VITE_POSTHOG_API_KEY;
    const apiHost = process.env.VITE_POSTHOG_API_HOST;

    if (!apiKey) {
      return;
    }

    this.client = new PostHog(apiKey, {
      host: apiHost || "https://internal-c.posthog.com",
      enableExceptionAutocapture: true,
    });

    this.getOrCreateSessionId();
  }

  setCurrentUserId(userId: string | null): void {
    this.currentUserId = userId;
  }

  getCurrentUserId(): string | null {
    return this.currentUserId;
  }

  getOrCreateSessionId(): string {
    if (!this.sessionId) {
      this.sessionId = uuidv7();
    }
    return this.sessionId;
  }

  setRendererSessionId(sessionId: string | null): void {
    this.rendererSessionId = sessionId;
  }

  getRendererSessionId(): string | null {
    return this.rendererSessionId;
  }

  track(eventName: string, properties?: AnalyticsProperties): void {
    if (!this.client) {
      return;
    }

    const distinctId = this.currentUserId || "anonymous-app-event";

    this.client.capture({
      distinctId,
      event: eventName,
      properties: {
        team: "posthog-code",
        // Joins main-process events into the same session as renderer and web
        // events. Only set while cross-surface stitching is enabled, because
        // the renderer pushes null otherwise.
        ...(this.rendererSessionId
          ? { $session_id: this.rendererSessionId }
          : {}),
        ...properties,
        app_version: getAppVersion(),
        os_platform: process.platform,
        os_arch: process.arch,
        $process_person_profile: !!this.currentUserId,
      },
    });
  }

  identify(userId: string, properties?: AnalyticsProperties): void {
    if (!this.client) {
      return;
    }

    this.currentUserId = userId;

    this.client.identify({
      distinctId: userId,
      properties,
    });
  }

  resetUser(): void {
    this.currentUserId = null;
  }

  captureException(
    error: unknown,
    additionalProperties?: Record<string, unknown>,
  ): void {
    if (!this.client) {
      return;
    }

    const distinctId = this.currentUserId || "anonymous-app-event";
    // Prefer the renderer's live session id: the boot id goes stale once the
    // renderer's posthog-js session rotates on idle or reset.
    const sessionId = this.rendererSessionId ?? this.sessionId;
    this.client.captureException(error, distinctId, {
      team: "posthog-code",
      ...additionalProperties,
      ...(sessionId ? { $session_id: sessionId } : {}),
      app_version: getAppVersion(),
      os_platform: process.platform,
      os_arch: process.arch,
    });
  }

  async flush(): Promise<void> {
    await this.client?.flush();
  }

  async shutdown(): Promise<void> {
    if (this.client) {
      await this.client.shutdown();
      this.client = null;
    }
  }
}

export const posthogNodeAnalytics = new PosthogNodeAnalytics();
