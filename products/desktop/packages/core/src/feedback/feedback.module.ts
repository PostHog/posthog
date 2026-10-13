import {
  FEEDBACK_SUBMISSION_SERVICE,
  FeedbackSubmissionService,
} from "@posthog/core/feedback/feedbackAttachmentService";
import { ContainerModule } from "inversify";

export const feedbackCoreModule = new ContainerModule(({ bind }) => {
  bind(FeedbackSubmissionService).toSelf().inSingletonScope();
  bind(FEEDBACK_SUBMISSION_SERVICE).toService(FeedbackSubmissionService);
});
