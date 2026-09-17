import { Eye, Paperclip } from "@phosphor-icons/react";
import type { IFeedbackContext } from "@posthog/platform/feedback-context";
import {
  Button,
  Checkbox,
  Field,
  FieldLabel,
  Text,
  Textarea,
} from "@posthog/quill";
import { toast } from "@posthog/ui/primitives/toast";
import {
  type ChangeEvent,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useRef,
  useState,
} from "react";
import {
  type FeedbackImage,
  MAX_FEEDBACK_IMAGE_COUNT,
  readFeedbackImage,
} from "./feedbackImages";

export interface FeedbackAttachmentsValue {
  includeScreenshot: boolean;
  includeLogs: boolean;
  logs: string | null;
  images: FeedbackImage[];
  logsLoading: boolean;
  imagesLoading: boolean;
}

interface FeedbackAttachmentsProps {
  screenshot: string | null;
  value: FeedbackAttachmentsValue;
  onChange: Dispatch<SetStateAction<FeedbackAttachmentsValue>>;
  contextClient: IFeedbackContext;
}

function AttachmentRow({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-8 min-w-0 items-center justify-between gap-3">
      {children}
    </div>
  );
}

function AttachmentPreviewButton({
  isVisible,
  label,
  dataAttr,
  onClick,
}: {
  isVisible: boolean;
  label: string;
  dataAttr: string;
  onClick: () => void;
}) {
  return (
    <Button
      variant="link-muted"
      size="xs"
      aria-label={`${isVisible ? "Hide" : "View"} ${label}`}
      data-attr={dataAttr}
      onPointerUp={(event) => event.currentTarget.blur()}
      onClick={onClick}
    >
      <Eye size={14} />
      {isVisible ? "Hide" : "View"}
    </Button>
  );
}

export function FeedbackAttachments({
  screenshot,
  value,
  onChange,
  contextClient,
}: FeedbackAttachmentsProps) {
  const [visibleAttachment, setVisibleAttachment] = useState<
    "screenshot" | "logs" | "images" | null
  >(null);
  const [logsUnavailable, setLogsUnavailable] = useState(false);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const logsRequestRef = useRef(0);

  const loadLogs = async (
    includeWhenLoaded: boolean,
  ): Promise<string | null> => {
    const requestId = ++logsRequestRef.current;
    onChange((current) => ({
      ...current,
      includeLogs: includeWhenLoaded ? true : current.includeLogs,
      logsLoading: true,
    }));
    setLogsUnavailable(false);
    try {
      const recentLogs = await contextClient.readRecentLogs().catch(() => null);
      if (logsRequestRef.current !== requestId) return null;
      onChange((current) => ({
        ...current,
        includeLogs: includeWhenLoaded
          ? recentLogs !== null
          : current.includeLogs,
        logs: recentLogs,
      }));
      setLogsUnavailable(!recentLogs);
      return recentLogs;
    } finally {
      if (logsRequestRef.current === requestId) {
        onChange((current) => ({ ...current, logsLoading: false }));
      }
    }
  };

  const handleIncludeLogsChange = async (checked: boolean) => {
    if (!checked) {
      logsRequestRef.current += 1;
      onChange((current) => ({
        ...current,
        includeLogs: false,
        logsLoading: false,
      }));
      return;
    }

    if (value.logs) {
      onChange((current) => ({ ...current, includeLogs: true }));
      return;
    }

    await loadLogs(true);
  };

  const handleToggleLogsPreview = async () => {
    if (visibleAttachment === "logs") {
      setVisibleAttachment(null);
      return;
    }

    if (!value.logs && !(await loadLogs(false))) return;
    setVisibleAttachment("logs");
  };

  const handleImageSelect = async (event: ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(event.currentTarget.files ?? []);
    event.currentTarget.value = "";
    const availableSlots = MAX_FEEDBACK_IMAGE_COUNT - value.images.length;
    if (selectedFiles.length > availableSlots) {
      toast.warning(`You can attach up to ${MAX_FEEDBACK_IMAGE_COUNT} images.`);
    }

    onChange((current) => ({ ...current, imagesLoading: true }));
    try {
      const nextImages = await Promise.all(
        selectedFiles.slice(0, availableSlots).map(async (file) => {
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
      onChange((current) => ({
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
      onChange((current) => ({ ...current, imagesLoading: false }));
    }
  };

  return (
    <div className="mt-1 flex flex-col border-gray-6 border-y py-1">
      <AttachmentRow>
        <Field orientation="horizontal" className="min-w-0 items-center gap-2">
          <Checkbox
            id="feedback-include-screenshot"
            data-attr="desktop-feedback-include-screenshot"
            checked={value.includeScreenshot}
            disabled={!screenshot}
            onCheckedChange={(checked) => {
              onChange((current) => ({
                ...current,
                includeScreenshot: checked === true,
              }));
              if (!checked && visibleAttachment === "screenshot") {
                setVisibleAttachment(null);
              }
            }}
          />
          <FieldLabel
            htmlFor="feedback-include-screenshot"
            className="font-normal"
          >
            {screenshot
              ? "Include screenshot of this window"
              : "Screenshot unavailable"}
          </FieldLabel>
        </Field>
        {screenshot && (
          <AttachmentPreviewButton
            isVisible={visibleAttachment === "screenshot"}
            label="screenshot"
            dataAttr="desktop-feedback-view-screenshot"
            onClick={() =>
              setVisibleAttachment((current) =>
                current === "screenshot" ? null : "screenshot",
              )
            }
          />
        )}
      </AttachmentRow>
      {screenshot && visibleAttachment === "screenshot" && (
        <div className="mb-2 ml-6 flex min-w-0 flex-col rounded border border-gray-6 p-2">
          <img
            src={screenshot}
            alt="App screenshot captured before this dialog opened"
            className="max-h-72 w-full rounded object-contain"
            data-ph-mask
          />
        </div>
      )}

      <AttachmentRow>
        <Field orientation="horizontal" className="min-w-0 items-center gap-2">
          <Checkbox
            id="feedback-include-logs"
            data-attr="desktop-feedback-include-logs"
            checked={value.includeLogs}
            onCheckedChange={(checked) =>
              void handleIncludeLogsChange(checked === true)
            }
          />
          <FieldLabel htmlFor="feedback-include-logs" className="font-normal">
            Include recent app logs
          </FieldLabel>
        </Field>
        <AttachmentPreviewButton
          isVisible={visibleAttachment === "logs"}
          label="app logs"
          dataAttr="desktop-feedback-view-logs"
          onClick={() => void handleToggleLogsPreview()}
        />
      </AttachmentRow>
      <Text size="xxs" variant="muted" className="mb-1 ml-6">
        Logs can contain file paths or personal data.
      </Text>
      {logsUnavailable && (
        <Text size="xxs" variant="muted" className="mb-1 ml-6">
          No recent app logs found.
        </Text>
      )}
      {value.logs && visibleAttachment === "logs" && (
        <div className="mb-2 ml-6 flex min-w-0 flex-col rounded border border-gray-6 p-2">
          <Textarea
            value={value.logs}
            readOnly
            rows={5}
            className="h-64 min-h-64 resize-none overflow-auto font-mono text-[11px] leading-4 [field-sizing:fixed]"
            aria-label="Recent app logs"
          />
        </div>
      )}

      <input
        ref={imageInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        multiple
        aria-label="Choose feedback images"
        className="hidden"
        onChange={(event) => void handleImageSelect(event)}
      />
      <div className="mt-2">
        <AttachmentRow>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="xs"
              loading={value.imagesLoading}
              disabled={value.images.length >= MAX_FEEDBACK_IMAGE_COUNT}
              data-attr="desktop-feedback-attach-images"
              onClick={() => imageInputRef.current?.click()}
            >
              <Paperclip size={14} />
              Attach images
            </Button>
            {value.images.length > 0 && (
              <Text size="xxs" variant="muted">
                {value.images.length} attached
              </Text>
            )}
          </div>
          {value.images.length > 0 && (
            <AttachmentPreviewButton
              isVisible={visibleAttachment === "images"}
              label="attached images"
              dataAttr="desktop-feedback-view-images"
              onClick={() =>
                setVisibleAttachment((current) =>
                  current === "images" ? null : "images",
                )
              }
            />
          )}
        </AttachmentRow>
      </div>
      {visibleAttachment === "images" && value.images.length > 0 && (
        <div className="mb-2 ml-6 grid min-w-0 grid-cols-2 gap-2">
          {value.images.map((image) => (
            <div
              key={image.id}
              className="flex min-w-0 flex-col gap-1 rounded border border-gray-6 p-2"
            >
              <img
                src={image.dataUrl}
                alt={`Attachment ${image.name}`}
                className="h-40 w-full rounded object-contain"
              />
              <div className="flex min-w-0 items-center justify-between gap-2">
                <Text size="xxs" className="truncate">
                  {image.name}
                </Text>
                <Button
                  variant="link-muted"
                  size="xs"
                  aria-label={`Remove ${image.name}`}
                  data-attr="desktop-feedback-remove-image"
                  onClick={() =>
                    onChange((current) => ({
                      ...current,
                      images: current.images.filter(
                        (item) => item.id !== image.id,
                      ),
                    }))
                  }
                >
                  Remove
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
