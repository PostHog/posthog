export interface IFeedbackContext {
  captureScreenshot(): Promise<string | null>;
  readRecentLogs(): Promise<string | null>;
}

export const FEEDBACK_CONTEXT_SERVICE = Symbol.for(
  "posthog.platform.feedbackContext",
);
