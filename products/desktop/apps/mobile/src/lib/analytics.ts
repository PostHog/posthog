import {
  type InboxReportActionProperties,
  type InboxReportClosedProperties,
  type InboxReportFeedbackNoteProperties,
  type InboxReportFeedbackProperties,
  type InboxReportOpenedProperties,
  type InboxReportScrolledProperties,
  type InboxViewedProperties,
  ANALYTICS_EVENTS as SHARED_ANALYTICS_EVENTS,
  type PromptSentProperties as SharedPromptSentProperties,
  type TaskRunStoppedProperties,
} from "@posthog/shared/analytics-events";
import { type PostHog, usePostHog } from "posthog-react-native";
import { useEffect, useMemo } from "react";

/**
 * The slice of the shared event vocabulary mobile fires, plus the sign-in
 * events only mobile has (desktop signs in through onboarding, which has its
 * own events). Sharing the names keeps desktop, cloud and mobile funnelling
 * into one bucket per event.
 */
export const ANALYTICS_EVENTS = {
  INBOX_VIEWED: SHARED_ANALYTICS_EVENTS.INBOX_VIEWED,
  INBOX_REPORT_OPENED: SHARED_ANALYTICS_EVENTS.INBOX_REPORT_OPENED,
  INBOX_REPORT_CLOSED: SHARED_ANALYTICS_EVENTS.INBOX_REPORT_CLOSED,
  INBOX_REPORT_SCROLLED: SHARED_ANALYTICS_EVENTS.INBOX_REPORT_SCROLLED,
  INBOX_REPORT_ACTION: SHARED_ANALYTICS_EVENTS.INBOX_REPORT_ACTION,
  INBOX_REPORT_FEEDBACK: SHARED_ANALYTICS_EVENTS.INBOX_REPORT_FEEDBACK,
  INBOX_REPORT_FEEDBACK_NOTE:
    SHARED_ANALYTICS_EVENTS.INBOX_REPORT_FEEDBACK_NOTE,
  PROMPT_SENT: SHARED_ANALYTICS_EVENTS.PROMPT_SENT,
  TASK_RUN_STOPPED: SHARED_ANALYTICS_EVENTS.TASK_RUN_STOPPED,
  SIGN_IN_STARTED: "Sign in started",
  SIGN_IN_COMPLETED: "Sign in completed",
  SIGN_IN_FAILED: "Sign in failed",
} as const;

export type SignInMethod = "oauth" | "dev_api_key" | "qr_scan";

export type SignInFailureReason = "cancelled" | "timeout" | "error";

export interface SignInStartedProperties {
  method: SignInMethod;
  region: string;
}

export interface SignInCompletedProperties {
  method: SignInMethod;
  region: string;
}

export interface SignInFailedProperties {
  method: SignInMethod;
  region: string;
  reason: SignInFailureReason;
  error_message: string;
}

/**
 * Mobile always runs cloud tasks, and steering is a mobile-only affordance, so
 * the shared shape is narrowed and extended rather than reused verbatim.
 */
export interface PromptSentProperties extends SharedPromptSentProperties {
  execution_type: "cloud";
  /** True when the message interrupted a running turn (Steer mode). */
  is_steer: boolean;
}

export type EventPropertyMap = {
  [ANALYTICS_EVENTS.INBOX_VIEWED]: InboxViewedProperties;
  [ANALYTICS_EVENTS.INBOX_REPORT_OPENED]: InboxReportOpenedProperties;
  [ANALYTICS_EVENTS.INBOX_REPORT_CLOSED]: InboxReportClosedProperties;
  [ANALYTICS_EVENTS.INBOX_REPORT_SCROLLED]: InboxReportScrolledProperties;
  [ANALYTICS_EVENTS.INBOX_REPORT_ACTION]: InboxReportActionProperties;
  [ANALYTICS_EVENTS.INBOX_REPORT_FEEDBACK]: InboxReportFeedbackProperties;
  [ANALYTICS_EVENTS.INBOX_REPORT_FEEDBACK_NOTE]: InboxReportFeedbackNoteProperties;
  [ANALYTICS_EVENTS.SIGN_IN_STARTED]: SignInStartedProperties;
  [ANALYTICS_EVENTS.SIGN_IN_COMPLETED]: SignInCompletedProperties;
  [ANALYTICS_EVENTS.SIGN_IN_FAILED]: SignInFailedProperties;
  [ANALYTICS_EVENTS.PROMPT_SENT]: PromptSentProperties;
  [ANALYTICS_EVENTS.TASK_RUN_STOPPED]: TaskRunStoppedProperties;
};

export interface Analytics {
  track<K extends keyof EventPropertyMap>(
    eventName: K,
    properties: EventPropertyMap[K],
  ): void;
}

type PostHogCaptureProperties = Parameters<PostHog["capture"]>[1];

// Client discriminator stamped on inbox events so the shared PostHog project
// can be sliced by surface (desktop sends "code", the web frontend sends
// "cloud"). Mirrors packages/ui/src/shell/posthogAnalyticsImpl.ts.
const INBOX_CLIENT = "mobile" as const;

export const INBOX_ANALYTICS_EVENT_NAMES: ReadonlySet<string> = new Set([
  ANALYTICS_EVENTS.INBOX_VIEWED,
  ANALYTICS_EVENTS.INBOX_REPORT_OPENED,
  ANALYTICS_EVENTS.INBOX_REPORT_CLOSED,
  ANALYTICS_EVENTS.INBOX_REPORT_SCROLLED,
  ANALYTICS_EVENTS.INBOX_REPORT_ACTION,
  ANALYTICS_EVENTS.INBOX_REPORT_FEEDBACK,
  ANALYTICS_EVENTS.INBOX_REPORT_FEEDBACK_NOTE,
]);

export function useAnalytics(): Analytics {
  const posthog = usePostHog();
  return useMemo<Analytics>(
    () => ({
      track: (eventName, properties) => {
        // Spread first so a caller could override the client, matching desktop.
        const enriched = INBOX_ANALYTICS_EVENT_NAMES.has(eventName)
          ? { inbox_client: INBOX_CLIENT, ...properties }
          : properties;
        posthog?.capture(
          eventName,
          enriched as unknown as PostHogCaptureProperties,
        );
      },
    }),
    [posthog],
  );
}

/**
 * Tag every subsequent PostHog event with `signal_report_id` for as long as
 * the calling screen is mounted with a non-null `signalReportId`. Clears the
 * super-property on unmount or when `signalReportId` becomes null. Mirrors the
 * desktop `setActiveTaskAnalyticsContext` super-property behaviour so events
 * fired while inside a discuss-launched task can be filtered down to a single
 * inbox report.
 */
export function useActiveTaskAnalyticsContext(
  signalReportId: string | null | undefined,
): void {
  const posthog = usePostHog();
  useEffect(() => {
    if (!posthog || !signalReportId) return;
    posthog.register({ signal_report_id: signalReportId });
    return () => {
      posthog.unregister("signal_report_id");
    };
  }, [posthog, signalReportId]);
}

/** Report age at fire time in hours, rounded to one decimal. Clamped at 0 to guard against clock skew. */
export function computeReportAgeHours(
  createdAt: string | null | undefined,
): number {
  if (!createdAt) return 0;
  const ageMs = Date.now() - new Date(createdAt).getTime();
  if (!Number.isFinite(ageMs)) return 0;
  return Math.max(0, Math.round((ageMs / 3_600_000) * 10) / 10);
}
