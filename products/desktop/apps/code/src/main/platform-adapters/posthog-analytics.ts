import type {
  AnalyticsProperties,
  IAnalytics,
} from "@posthog/platform/analytics";
import { PostHog } from "posthog-node";
import { getAppVersion } from "../utils/env";
import { uuidv7 } from "../utils/uuidv7";

class PosthogNodeAnalytics implements IAnalytics {
  private client: PostHog | null = null;
  private currentUserId: string | null = null;
  private sessionId: string | null = null;

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
    this.sendException(error, additionalProperties, this.sessionId);
  }

  /**
   * Capture a fault that happened in an earlier run of the app.
   *
   * The session of the run that faulted is not knowable after that run ends,
   * and the current session belongs to the launch that reports the fault. So
   * the event carries no session id, because the current one would link the
   * issue to a recording made after the fault.
   */
  captureDeferredException(
    error: unknown,
    additionalProperties?: Record<string, unknown>,
  ): void {
    this.sendException(error, additionalProperties, null);
  }

  private sendException(
    error: unknown,
    additionalProperties: Record<string, unknown> | undefined,
    sessionId: string | null,
  ): void {
    if (!this.client) {
      return;
    }

    const distinctId = this.currentUserId || "anonymous-app-event";
    const properties: Record<string, unknown> = {
      team: "posthog-code",
      ...additionalProperties,
      app_version: getAppVersion(),
      os_platform: process.platform,
      os_arch: process.arch,
    };
    // This adapter owns the session id, so a caller cannot supply one.
    delete properties.$session_id;
    if (sessionId) {
      properties.$session_id = sessionId;
    }
    this.client.captureException(error, distinctId, properties);
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
