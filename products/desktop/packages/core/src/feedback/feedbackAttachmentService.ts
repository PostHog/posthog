import type { AuthService } from "@posthog/core/auth/auth";
import { AUTH_SERVICE } from "@posthog/core/auth/auth.module";
import type {
  FeedbackImageUpload,
  FeedbackSubmissionInput,
} from "@posthog/platform/feedback-context";
import { inject, injectable } from "inversify";

export const FEEDBACK_SUBMISSION_SERVICE = Symbol.for(
  "posthog.core.feedback.submissionService",
);

export interface IFeedbackSubmissionService {
  submitFeedback(
    input: FeedbackSubmissionInput & { appVersion?: string },
  ): Promise<void>;
}

function dataUrlToBlob(dataUrl: string): Blob {
  const match = /^data:(image\/(?:jpeg|png|webp));base64,(.+)$/.exec(dataUrl);
  if (!match) throw new Error("Unsupported feedback image");

  const decoded = atob(match[2]);
  const buffer = new ArrayBuffer(decoded.length);
  const bytes = new Uint8Array(buffer);
  for (let index = 0; index < decoded.length; index += 1) {
    bytes[index] = decoded.charCodeAt(index);
  }
  return new Blob([buffer], { type: match[1] });
}

@injectable()
export class FeedbackSubmissionService implements IFeedbackSubmissionService {
  public constructor(
    @inject(AUTH_SERVICE)
    private readonly authService: AuthService,
  ) {}

  public async submitFeedback(
    input: FeedbackSubmissionInput & { appVersion?: string },
  ): Promise<void> {
    const { apiHost } = await this.authService.getValidAccessToken();
    const form = new FormData();
    form.append("response", input.response);
    form.append("source", input.source);
    form.append("feedback_view", input.feedbackView);
    if (input.feedbackTaskId) {
      form.append("feedback_task_id", input.feedbackTaskId);
    }
    if (input.feedbackFolderId) {
      form.append("feedback_folder_id", input.feedbackFolderId);
    }
    if (input.feedbackAppLogs) {
      form.append("feedback_app_logs", input.feedbackAppLogs);
    }
    if (input.appVersion) form.append("app_version", input.appVersion);
    if (input.sessionId) form.append("session_id", input.sessionId);
    if (input.screenshot) {
      appendImage(form, "screenshot", input.screenshot);
    }
    input.images.forEach((image, index) => {
      appendImage(form, `image_${index + 1}`, image);
    });

    const response = await this.authService.authenticatedFetch(
      fetch,
      `${apiHost}/api/desktop_feedback/`,
      { method: "POST", body: form },
    );
    if (!response.ok) {
      throw new Error(`Could not send feedback (${response.status})`);
    }

    const payload = (await response.json()) as {
      accepted?: unknown;
      response_id?: unknown;
    };
    if (payload.accepted !== true || typeof payload.response_id !== "string") {
      throw new Error("Feedback response was not accepted");
    }
  }
}

function appendImage(
  form: FormData,
  field: string,
  image: FeedbackImageUpload,
): void {
  form.append(field, dataUrlToBlob(image.dataUrl), image.name);
}
