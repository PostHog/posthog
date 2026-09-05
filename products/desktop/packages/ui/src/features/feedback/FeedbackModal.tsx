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
import { useEffect, useState } from "react";
import type { FeedbackModalMode } from "./feedbackStore";

export type { FeedbackModalMode } from "./feedbackStore";

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

function ScreenshotPreview({ dataUrl }: { dataUrl: string }) {
  const [previewUrl, setPreviewUrl] = useState("");

  useEffect(() => {
    if (typeof URL.createObjectURL !== "function") return;
    const [metadata, encoded] = dataUrl.split(",", 2);
    if (!metadata || !encoded) return;
    const mimeType = metadata.match(/^data:([^;]+);base64$/)?.[1];
    if (!mimeType) return;

    const decoded = atob(encoded);
    const bytes = Uint8Array.from(decoded, (character) =>
      character.charCodeAt(0),
    );
    const objectUrl = URL.createObjectURL(
      new Blob([bytes], { type: mimeType }),
    );
    setPreviewUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [dataUrl]);

  return (
    <img
      src={previewUrl || undefined}
      alt="App screenshot captured before this dialog opened"
      className="max-h-48 w-full rounded border border-gray-6 object-contain"
      data-ph-mask
    />
  );
}

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
      <DialogContent showCloseButton={false} className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{mode ? MODAL_COPY[mode].title : ""}</DialogTitle>
          <DialogDescription className="text-base text-gray-12">
            {mode ? MODAL_COPY[mode].prompt : ""}
          </DialogDescription>
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
  const [screenshot, setScreenshot] = useState(initialScreenshot);
  const [logs, setLogs] = useState<string | null>(null);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsUnavailable, setLogsUnavailable] = useState(false);

  const handleAttachLogs = async () => {
    setLogsLoading(true);
    setLogsUnavailable(false);
    const recentLogs = await contextClient.readRecentLogs().catch(() => null);
    setLogs(recentLogs);
    setLogsUnavailable(!recentLogs);
    setLogsLoading(false);
  };

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
        ...(screenshot ? { feedback_screenshot_data_url: screenshot } : {}),
        ...(logs ? { feedback_app_logs: logs } : {}),
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
            App and page details are included. Do not include passwords or other
            secrets.
          </Text>
          {mode === "feedback" && (
            <div className="mt-2 flex flex-col gap-3">
              {screenshot ? (
                <div className="flex flex-col gap-2 rounded border border-gray-6 p-2">
                  <div className="flex items-center justify-between gap-2">
                    <Text size="xs" weight="medium">
                      Screenshot attached
                    </Text>
                    <Button
                      variant="link-muted"
                      size="xs"
                      onClick={() => setScreenshot(null)}
                    >
                      Remove
                    </Button>
                  </div>
                  <ScreenshotPreview dataUrl={screenshot} />
                  <Text size="xxs" variant="muted">
                    Review the screenshot before you send it. Remove it if it
                    contains sensitive information.
                  </Text>
                </div>
              ) : (
                <Text size="xxs" variant="muted">
                  A screenshot could not be captured.
                </Text>
              )}

              {logs ? (
                <div className="flex flex-col gap-2 rounded border border-gray-6 p-2">
                  <div className="flex items-center justify-between gap-2">
                    <Text size="xs" weight="medium">
                      Recent app logs attached
                    </Text>
                    <Button
                      variant="link-muted"
                      size="xs"
                      onClick={() => setLogs(null)}
                    >
                      Remove
                    </Button>
                  </div>
                  <Textarea
                    value={logs}
                    readOnly
                    rows={5}
                    className="font-mono text-xs"
                    aria-label="Recent app logs"
                  />
                  <Text size="xxs" variant="muted">
                    Review these logs before you send them. They can include
                    file paths, task details, or other sensitive information.
                  </Text>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="xs"
                    loading={logsLoading}
                    onClick={() => void handleAttachLogs()}
                  >
                    Attach recent app logs
                  </Button>
                  {logsUnavailable && (
                    <Text size="xxs" variant="muted">
                      No recent app logs found.
                    </Text>
                  )}
                </div>
              )}
            </div>
          )}
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
