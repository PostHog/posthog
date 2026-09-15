import type { IFeedbackContext } from "@posthog/platform/feedback-context";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Kbd,
  Text,
  Textarea,
} from "@posthog/quill";
import { formatHotkey } from "@posthog/ui/features/command/keyboard-shortcuts";
import { FEEDBACK_SOURCE_BY_MODE } from "@posthog/ui/features/feedback/feedbackSurvey";
import { toast } from "@posthog/ui/primitives/toast";
import { getAppViewSnapshot } from "@posthog/ui/router/useAppView";
import {
  captureException,
  getAnalyticsSessionId,
} from "@posthog/ui/shell/analytics";
import { useEffect, useState } from "react";
import {
  FeedbackAttachments,
  type FeedbackAttachmentsValue,
} from "./FeedbackAttachments";
import type { FeedbackModalMode } from "./feedbackStore";

export type { FeedbackModalMode } from "./feedbackStore";

const MODAL_COPY: Record<
  FeedbackModalMode,
  { title: string; description?: string; placeholder: string }
> = {
  feedback: {
    title: "What should we improve in PostHog Desktop?",
    placeholder: "What happened, and what did you expect?",
  },
  "posthog-web": {
    title: "Before you head to PostHog web",
    description: "Why are you going back to PostHog web?",
    placeholder: "What are you looking for in PostHog web?",
  },
};

export interface FeedbackModalProps {
  mode: FeedbackModalMode | null;
  onFinished: () => void;
  contextClient: IFeedbackContext;
}

export function FeedbackModal({
  mode,
  onFinished,
  contextClient,
}: FeedbackModalProps) {
  const open = mode !== null;
  const copy = mode ? MODAL_COPY[mode] : null;
  const [capturedScreenshot, setCapturedScreenshot] = useState<{
    mode: FeedbackModalMode;
    dataUrl: string | null;
  } | null>(null);

  useEffect(() => {
    if (mode !== "feedback") return;
    let active = true;
    setCapturedScreenshot(null);
    void contextClient
      .captureScreenshot()
      .catch(() => null)
      .then((dataUrl) => {
        if (active) setCapturedScreenshot({ mode, dataUrl });
      });
    return () => {
      active = false;
    };
  }, [mode, contextClient]);

  if (
    mode === "feedback" &&
    (!capturedScreenshot || capturedScreenshot.mode !== mode)
  ) {
    return null;
  }

  const handleFinished = () => {
    setCapturedScreenshot(null);
    onFinished();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(isOpen) => {
        if (!isOpen) handleFinished();
      }}
    >
      <DialogContent
        showCloseButton={false}
        className="ph-no-capture sm:max-w-lg"
      >
        <DialogHeader>
          <DialogTitle>{copy?.title ?? ""}</DialogTitle>
          {copy?.description && (
            <DialogDescription>{copy.description}</DialogDescription>
          )}
        </DialogHeader>
        {mode !== null && (
          <FeedbackModalForm
            mode={mode}
            onFinished={handleFinished}
            contextClient={contextClient}
            initialScreenshot={capturedScreenshot?.dataUrl ?? null}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function FeedbackModalForm({
  mode,
  onFinished,
  contextClient,
  initialScreenshot,
}: {
  mode: FeedbackModalMode;
  onFinished: () => void;
  contextClient: IFeedbackContext;
  initialScreenshot: string | null;
}) {
  const [value, setValue] = useState("");
  const [view] = useState(getAppViewSnapshot);
  const [submitting, setSubmitting] = useState(false);
  const [attachments, setAttachments] = useState<FeedbackAttachmentsValue>({
    includeScreenshot: false,
    includeLogs: false,
    logs: null,
    images: [],
    logsLoading: false,
    imagesLoading: false,
  });
  const canSubmit =
    value.trim().length > 0 &&
    !submitting &&
    !attachments.logsLoading &&
    !attachments.imagesLoading;

  const handleSubmit = async () => {
    const response = value.trim();
    if (!canSubmit || !response) return;
    setSubmitting(true);
    try {
      const includeScreenshot =
        attachments.includeScreenshot && initialScreenshot !== null;
      const sessionId = getAnalyticsSessionId();
      await contextClient.submitFeedback({
        response,
        source: FEEDBACK_SOURCE_BY_MODE[mode],
        feedbackView: view.type,
        ...(view.taskId ? { feedbackTaskId: view.taskId } : {}),
        ...(view.folderId ? { feedbackFolderId: view.folderId } : {}),
        ...(attachments.includeLogs && attachments.logs
          ? { feedbackAppLogs: attachments.logs }
          : {}),
        ...(sessionId ? { sessionId } : {}),
        ...(includeScreenshot && initialScreenshot
          ? {
              screenshot: {
                name: "posthog-desktop-screenshot.jpg",
                dataUrl: initialScreenshot,
              },
            }
          : {}),
        images: attachments.images,
      });
      toast.success("Feedback sent");
      onFinished();
    } catch (error) {
      captureException(
        error instanceof Error ? error : new Error("Could not send feedback"),
        { feedback_stage: "submission" },
      );
      toast.error("Could not send feedback. Try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <DialogBody>
        <div className="flex flex-col gap-3">
          <Textarea
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={MODAL_COPY[mode].placeholder}
            rows={4}
            maxLength={4000}
            autoFocus
            className="focus-visible:shadow-none"
            aria-keyshortcuts="Meta+Enter Control+Enter"
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                void handleSubmit();
              }
            }}
          />
          {mode === "feedback" && (
            <>
              <Text size="xxs" variant="muted" className="mt-1">
                Always included: app version and current page.
              </Text>
              <FeedbackAttachments
                screenshot={initialScreenshot}
                value={attachments}
                onChange={setAttachments}
                contextClient={contextClient}
              />
            </>
          )}
        </div>
      </DialogBody>
      <DialogFooter className="border-t-0">
        <Button variant="outline" size="sm" onClick={onFinished}>
          {mode === "feedback" ? "Cancel" : "Skip"}
        </Button>
        <Button
          variant={canSubmit ? "primary" : "outline"}
          size="sm"
          loading={submitting}
          focusableWhenDisabled={false}
          disabled={!canSubmit}
          aria-label="Send feedback"
          onClick={() => void handleSubmit()}
        >
          Send feedback
          <Kbd aria-hidden="true" className="ml-1">
            {formatHotkey("mod+enter")}
          </Kbd>
        </Button>
      </DialogFooter>
    </>
  );
}
