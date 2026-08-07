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
    this.client.captureException(error, distinctId, {
      team: "posthog-code",
      ...additionalProperties,
      ...(this.sessionId ? { $session_id: this.sessionId } : {}),
      app_version: getAppVersion(),
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
