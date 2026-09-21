export interface FeedbackImageUpload {
  name: string;
  dataUrl: string;
}

export interface FeedbackSubmissionInput {
  response: string;
  source: string;
  feedbackView: string;
  feedbackTaskId?: string;
  feedbackFolderId?: string;
  feedbackAppLogs?: string;
  sessionId?: string;
  screenshot?: FeedbackImageUpload;
  images: FeedbackImageUpload[];
}

export interface IFeedbackContext {
  captureScreenshot(): Promise<string | null>;
  readRecentLogs(): Promise<string | null>;
  submitFeedback(input: FeedbackSubmissionInput): Promise<void>;
}

export const FEEDBACK_CONTEXT_SERVICE = Symbol.for(
  "posthog.platform.feedbackContext",
);
