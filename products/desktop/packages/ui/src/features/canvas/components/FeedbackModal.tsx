import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Textarea,
} from "@posthog/quill";
import {
  FEEDBACK_SOURCE_BY_MODE,
  FEEDBACK_SURVEY_ID,
  FEEDBACK_SURVEY_QUESTION_ID,
  FEEDBACK_SURVEY_SOURCE_QUESTION_ID,
} from "@posthog/ui/features/canvas/feedbackSurvey";
import { captureSurveyResponse } from "@posthog/ui/shell/analytics";
import { useState } from "react";

export type FeedbackModalMode = "feedback" | "posthog-web";

/** Title + prompt shown for each way the modal can be opened. */
const MODAL_COPY: Record<FeedbackModalMode, { title: string; prompt: string }> =
  {
    feedback: {
      title: "Leave feedback",
      prompt:
        "How's the Channels experience? Tell us what's working and what you'd change.",
    },
    "posthog-web": {
      title: "Before you head to PostHog web",
      prompt: "Why are you going back to PostHog web?",
    },
  };

export interface FeedbackModalProps {
  /** `null` closes the modal. `"feedback"` shows a Cancel button; the navigation-intercept mode (`"posthog-web"`) shows a Skip button. */
  mode: FeedbackModalMode | null;
  /** Called after the response is submitted, and when the modal is skipped/cancelled/dismissed. */
  onFinished: () => void;
}

/**
 * Feedback modal for the Channels space. Submitting records the text as a
 * PostHog survey response (see {@link FEEDBACK_SURVEY_ID}) along with where the
 * modal was opened from. The secondary button reads "Skip" when the modal
 * intercepts a navigation (`"posthog-web"`) and "Cancel" when opened directly
 * by "Leave feedback".
 */
export function FeedbackModal({ mode, onFinished }: FeedbackModalProps) {
  const open = mode !== null;

  return (
    <Dialog
      open={open}
      onOpenChange={(isOpen) => {
        // Esc / outside-click dismiss behaves like the secondary button.
        if (!isOpen) onFinished();
      }}
    >
      <DialogContent showCloseButton={false} className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{mode ? MODAL_COPY[mode].title : ""}</DialogTitle>
          {/* The prompt is the question we want answered, so render it at full
              contrast rather than the muted default. */}
          <DialogDescription className="text-base text-gray-12">
            {mode ? MODAL_COPY[mode].prompt : ""}
          </DialogDescription>
        </DialogHeader>
        {/* Mounted only while open so the textarea resets on each open without
            syncing state to the `mode` prop in an effect. */}
        {mode !== null && (
          <FeedbackModalForm mode={mode} onFinished={onFinished} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function FeedbackModalForm({
  mode,
  onFinished,
}: {
  mode: FeedbackModalMode;
  onFinished: () => void;
}) {
  const [value, setValue] = useState("");

  const handleSubmit = () => {
    const response = value.trim();
    if (!response) return;
    captureSurveyResponse({
      surveyId: FEEDBACK_SURVEY_ID,
      responses: [
        { questionId: FEEDBACK_SURVEY_QUESTION_ID, response },
        {
          questionId: FEEDBACK_SURVEY_SOURCE_QUESTION_ID,
          response: FEEDBACK_SOURCE_BY_MODE[mode],
        },
      ],
    });
    onFinished();
  };

  return (
    <>
      <DialogBody>
        <Textarea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Share your feedback"
          rows={4}
          maxLength={4000}
          autoFocus
        />
      </DialogBody>
      <DialogFooter>
        <Button variant="outline" size="sm" onClick={onFinished}>
          {mode === "feedback" ? "Cancel" : "Skip"}
        </Button>
        <Button
          variant="primary"
          size="sm"
          disabled={value.trim().length === 0}
          onClick={handleSubmit}
        >
          Send feedback
        </Button>
      </DialogFooter>
    </>
  );
}
