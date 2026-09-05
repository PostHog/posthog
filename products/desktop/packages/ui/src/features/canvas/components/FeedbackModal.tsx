import { useService } from "@posthog/di/react";
import {
  FEEDBACK_CONTEXT_SERVICE,
  type IFeedbackContext,
} from "@posthog/platform/feedback-context";
import {
  FeedbackModal as ContextualFeedbackModal,
  type FeedbackModalProps,
} from "@posthog/ui/features/feedback/FeedbackModal";

export type { FeedbackModalMode } from "@posthog/ui/features/feedback/feedbackStore";

type LegacyFeedbackModalProps = Omit<FeedbackModalProps, "contextClient">;

export function FeedbackModal(props: LegacyFeedbackModalProps) {
  const contextClient = useService<IFeedbackContext>(FEEDBACK_CONTEXT_SERVICE);
  return <ContextualFeedbackModal {...props} contextClient={contextClient} />;
}
