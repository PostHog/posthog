import type {
  FeedbackSubmissionInput,
  IFeedbackContext,
} from "@posthog/platform/feedback-context";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  FieldLabel,
  Kbd,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
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
import { useEffect, useRef, useState } from "react";
import {
  FeedbackAttachments,
  type FeedbackAttachmentsValue,
} from "./FeedbackAttachments";
import {
  type FeedbackImage,
  MAX_FEEDBACK_IMAGE_COUNT,
  readFeedbackImage,
} from "./feedbackImages";
import type { FeedbackModalMode } from "./feedbackStore";

export type { FeedbackModalMode } from "./feedbackStore";

const FEEDBACK_TYPES = [
  { value: "bug", label: "Bug" },
  { value: "feature", label: "Feature" },
  { value: "general", label: "General" },
] satisfies {
  value: NonNullable<FeedbackSubmissionInput["feedbackType"]>;
  label: string;
}[];

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
  const [feedbackType, setFeedbackType] =
    useState<NonNullable<FeedbackSubmissionInput["feedbackType"]>>("general");
  const [view] = useState(getAppViewSnapshot);
  const [submitting, setSubmitting] = useState(false);
  const imagesLoadingRef = useRef(false);
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
    if (!canSubmit || imagesLoadingRef.current || !response) return;
    setSubmitting(true);
    try {
      const includeScreenshot =
        attachments.includeScreenshot && initialScreenshot !== null;
      const sessionId = getAnalyticsSessionId();
      await contextClient.submitFeedback({
        response,
        source: FEEDBACK_SOURCE_BY_MODE[mode],
        ...(mode === "feedback" ? { feedbackType } : {}),
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

  const handleImageFiles = async (files: File[]): Promise<void> => {
    if (submitting || files.length === 0) return;
    if (imagesLoadingRef.current) {
      toast.warning("An image is still loading. Wait, then paste it again.");
      return;
    }
    const availableSlots = MAX_FEEDBACK_IMAGE_COUNT - attachments.images.length;
    if (files.length > availableSlots) {
      toast.warning(`You can attach up to ${MAX_FEEDBACK_IMAGE_COUNT} images.`);
    }
    if (availableSlots === 0) return;
    imagesLoadingRef.current = true;
    setAttachments((current) => ({ ...current, imagesLoading: true }));
    try {
      const nextImages = await Promise.all(
        files.slice(0, availableSlots).map(async (file) => {
          try {
            return await readFeedbackImage(file);
          } catch (error) {
            toast.error(
              error instanceof Error
                ? error.message
                : "Could not attach this image.",
            );
            return null;
          }
        }),
      );
      setAttachments((current) => ({
        ...current,
        images: [
          ...current.images,
          ...nextImages.filter(
            (image): image is FeedbackImage =>
              image !== null &&
              !current.images.some((existing) => existing.id === image.id),
          ),
        ].slice(0, MAX_FEEDBACK_IMAGE_COUNT),
      }));
    } finally {
      imagesLoadingRef.current = false;
      setAttachments((current) => ({ ...current, imagesLoading: false }));
    }
  };

  return (
    <>
      <DialogBody>
        <div className="flex flex-col gap-3">
          {mode === "feedback" && (
            <Field className="gap-1">
              <FieldLabel htmlFor="feedback-type">Feedback type</FieldLabel>
              <Select
                value={feedbackType}
                items={FEEDBACK_TYPES}
                disabled={submitting}
                onValueChange={(next) => {
                  if (next) setFeedbackType(next);
                }}
              >
                <SelectTrigger id="feedback-type" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {FEEDBACK_TYPES.map((type) => (
                    <SelectItem key={type.value} value={type.value}>
                      {type.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          )}
          <Textarea
            value={value}
            disabled={submitting}
            onChange={(event) => setValue(event.target.value)}
            onPaste={(event) => {
              if (mode !== "feedback") return;
              const files = Array.from(event.clipboardData.files).filter(
                (file) => !file.type || file.type.startsWith("image/"),
              );
              if (files.length === 0) return;
              if (!event.clipboardData.getData("text/plain"))
                event.preventDefault();
              void handleImageFiles(files);
            }}
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
              <fieldset disabled={submitting} className="min-w-0">
                <FeedbackAttachments
                  screenshot={initialScreenshot}
                  value={attachments}
                  onChange={setAttachments}
                  onImageFiles={handleImageFiles}
                  contextClient={contextClient}
                />
              </fieldset>
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
