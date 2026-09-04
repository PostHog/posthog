import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Text,
  Textarea,
} from "@posthog/quill";
import {
  FEEDBACK_SOURCE_BY_MODE,
  FEEDBACK_SURVEY_ID,
  FEEDBACK_SURVEY_QUESTION_ID,
  FEEDBACK_SURVEY_SOURCE_QUESTION_ID,
} from "@posthog/ui/features/feedback/feedbackSurvey";
import { toast } from "@posthog/ui/primitives/toast";
import { getAppViewSnapshot } from "@posthog/ui/router/useAppView";
import { captureSurveyResponse } from "@posthog/ui/shell/analytics";
import { useState } from "react";

export type FeedbackModalMode = "feedback" | "posthog-web";

const MODAL_COPY: Record<FeedbackModalMode, { title: string; prompt: string }> =
  {
    feedback: {
      title: "Send feedback",
      prompt: "What should we improve in PostHog Desktop?",
    },
    "posthog-web": {
      title: "Before you head to PostHog web",
      prompt: "Why are you going back to PostHog web?",
    },
  };

export interface FeedbackModalProps {
  mode: FeedbackModalMode | null;
  onFinished: () => void;
}

export function FeedbackModal({ mode, onFinished }: FeedbackModalProps) {
  const open = mode !== null;

  return (
    <Dialog
      open={open}
      onOpenChange={(isOpen) => {
        if (!isOpen) onFinished();
      }}
    >
      <DialogContent showCloseButton={false} className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{mode ? MODAL_COPY[mode].title : ""}</DialogTitle>
          <DialogDescription className="text-base text-gray-12">
            {mode ? MODAL_COPY[mode].prompt : ""}
          </DialogDescription>
        </DialogHeader>
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
    const view = getAppViewSnapshot();

    captureSurveyResponse({
      surveyId: FEEDBACK_SURVEY_ID,
      responses: [
        { questionId: FEEDBACK_SURVEY_QUESTION_ID, response },
        {
          questionId: FEEDBACK_SURVEY_SOURCE_QUESTION_ID,
          response: FEEDBACK_SOURCE_BY_MODE[mode],
        },
      ],
      additionalProperties: {
        feedback_view: view.type,
        ...(view.taskId ? { feedback_task_id: view.taskId } : {}),
        ...(view.folderId ? { feedback_folder_id: view.folderId } : {}),
      },
    });
    toast.success("Feedback sent");
    onFinished();
  };

  return (
    <>
      <DialogBody>
        <div className="flex flex-col gap-2">
          <Textarea
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="Share your feedback"
            rows={4}
            maxLength={4000}
            autoFocus
          />
          <Text size="xxs" variant="muted">
            We include app and page details, and related task or folder IDs. Do
            not include passwords or other secrets.
          </Text>
        </div>
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
