import { useService } from "@posthog/di/react";
import {
  FEEDBACK_CONTEXT_SERVICE,
  type IFeedbackContext,
} from "@posthog/platform/feedback-context";
import { FeedbackModal } from "@posthog/ui/features/feedback/FeedbackModal";
import { useFeedbackStore } from "@posthog/ui/features/feedback/feedbackStore";

export function FeedbackHost() {
  const mode = useFeedbackStore((state) => state.mode);
  const closeFeedback = useFeedbackStore((state) => state.close);
  const feedbackContext = useService<IFeedbackContext>(
    FEEDBACK_CONTEXT_SERVICE,
  );

  return (
    <FeedbackModal
      mode={mode}
      onFinished={closeFeedback}
      contextClient={feedbackContext}
    />
  );
}
