import type { PostHogEventProperties } from "@posthog/core";
import { usePostHog } from "posthog-react-native";
import { useEffect, useMemo } from "react";

/**
 * Event names mirror packages/shared/src/analytics-events.ts so PostHog reports
 * funnel the same events from desktop and mobile into a single bucket.
 */
export const ANALYTICS_EVENTS = {
  INBOX_VIEWED: "Inbox viewed",
  INBOX_REPORT_OPENED: "Inbox report opened",
  INBOX_REPORT_CLOSED: "Inbox report closed",
  INBOX_REPORT_SCROLLED: "Inbox report scrolled",
  INBOX_REPORT_ACTION: "Inbox report action",
  SIGN_IN_STARTED: "Sign in started",
  SIGN_IN_COMPLETED: "Sign in completed",
  SIGN_IN_FAILED: "Sign in failed",
  PROMPT_SENT: "Prompt sent",
  TASK_RUN_STOPPED: "Task run stopped",
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

export type InboxReportOpenMethod =
  | "click"
  | "click_cmd"
  | "click_shift"
  | "keyboard"
  | "deeplink"
  | "unknown";

export type InboxReportCloseMethod =
  | "next_report"
  | "deselected"
  | "navigated_away"
  | "unmount";

export type InboxReportActionType =
  | "dismiss"
  | "snooze"
  | "delete"
  | "reingest"
  | "create_pr"
  | "open_pr"
  | "copy_link"
  | "discuss"
  | "expand_signal"
  | "collapse_signal"
  | "expand_signal_section"
  | "view_signal_external"
  | "expand_why"
  | "click_suggested_reviewer"
  | "add_suggested_reviewer"
  | "remove_suggested_reviewer"
  | "expand_task_section"
  | "play_session_recording";

export type InboxReportActionSurface =
  | "detail_pane"
  | "toolbar"
  | "keyboard"
  | "list_row";

export interface InboxViewedProperties {
  report_count: number;
  total_count: number;
  ready_count: number;
  has_active_filters: boolean;
  source_product_filter: string[];
  status_filter_count: number;
  is_empty: boolean;
  priority_p0_count: number;
  priority_p1_count: number;
  priority_p2_count: number;
  priority_p3_count: number;
  priority_p4_count: number;
  priority_unknown_count: number;
  actionability_immediately_actionable_count: number;
  actionability_requires_human_input_count: number;
  actionability_not_actionable_count: number;
  actionability_unknown_count: number;
}

export interface InboxReportOpenedProperties {
  report_id: string;
  report_title: string | null;
  report_age_hours: number;
  status: string | null;
  priority: string | null;
  actionability: string | null;
  source_products: string[];
  rank: number;
  list_size: number;
  open_method: InboxReportOpenMethod;
  previous_report_id: string | null;
}

export interface InboxReportClosedProperties {
  report_id: string;
  report_title: string | null;
  report_age_hours: number;
  priority: string | null;
  actionability: string | null;
  time_spent_ms: number;
  scrolled: boolean;
  close_method: InboxReportCloseMethod;
}

export interface InboxReportScrolledProperties {
  report_id: string;
  report_title: string | null;
  report_age_hours: number;
  priority: string | null;
  actionability: string | null;
  rank: number;
  list_size: number;
  time_since_open_ms: number;
}

export interface InboxReportActionProperties {
  report_id: string;
  report_title: string | null;
  report_age_hours: number;
  priority: string | null;
  actionability: string | null;
  action_type: InboxReportActionType;
  surface: InboxReportActionSurface;
  is_bulk: boolean;
  bulk_size: number;
  rank: number;
  list_size: number;
  dismissal_reason?: string;
  dismissal_note?: string;
  signal_id?: string;
  signal_source_product?: string;
  signal_source_type?: string;
  signal_section?: "relevant_code" | "data_queried";
  why_field?: "priority" | "actionability";
  task_section?: "research" | "implementation";
  has_question?: boolean;
  question_text?: string;
  has_feedback?: boolean;
  feedback_text?: string;
  suggested_reviewer_login?: string;
  suggested_reviewer_uuid?: string;
}

export interface PromptSentProperties {
  task_id: string;
  is_initial: boolean;
  execution_type: "cloud";
  prompt_length_chars: number;
  /** True when the message interrupted a running turn (Steer mode). */
  is_steer: boolean;
}

export interface TaskRunStoppedProperties {
  task_id: string;
  execution_type: "cloud";
  prompts_sent?: number;
}

export type EventPropertyMap = {
  [ANALYTICS_EVENTS.INBOX_VIEWED]: InboxViewedProperties;
  [ANALYTICS_EVENTS.INBOX_REPORT_OPENED]: InboxReportOpenedProperties;
  [ANALYTICS_EVENTS.INBOX_REPORT_CLOSED]: InboxReportClosedProperties;
  [ANALYTICS_EVENTS.INBOX_REPORT_SCROLLED]: InboxReportScrolledProperties;
  [ANALYTICS_EVENTS.INBOX_REPORT_ACTION]: InboxReportActionProperties;
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
        // Our typed property interfaces don't carry an index signature; cast
        // to the wider PostHog event-properties shape without losing the
        // narrower call-site type-check.
        posthog?.capture(
          eventName,
          enriched as unknown as PostHogEventProperties,
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
