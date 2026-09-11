import type { FileAttachment } from "@posthog/core/message-editor/content";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
  Text,
} from "@posthog/quill";
import {
  isGifFile,
  isRasterImageFile,
  parseImageDataUrl,
} from "@posthog/shared";
import {
  Attachment,
  type AttachmentUploadStatus,
} from "@posthog/ui/features/message-editor/components/Attachment";
import { SafeImagePreview } from "@posthog/ui/primitives/SafeImagePreview";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { readFileAsDataUrl } from "../hostApi";

export type { AttachmentUploadStatus };

/**
 * A GIF's first frame, drawn once to a canvas. An animating thumbnail in the
 * composer pulls the eye off what you are writing.
 */
function useFrozenGif(src: string | null | undefined, enabled: boolean) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!enabled || !src) return;
    const img = new Image();
    let cancelled = false;
    img.onload = () => {
      // A decode that lands after the src changed would paint the previous
      // GIF's frame onto the canvas the new one is about to use, and the
      // handler holds the decoded image alive until it fires.
      if (cancelled) return;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const size = 64;
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const min = Math.min(img.naturalWidth, img.naturalHeight);
      const sx = (img.naturalWidth - min) / 2;
      const sy = (img.naturalHeight - min) / 2;
      ctx.drawImage(img, sx, sy, min, min, 0, 0, size, size);
    };
    img.src = src;
    return () => {
      cancelled = true;
      img.onload = null;
    };
  }, [src, enabled]);

  return canvasRef;
}

function ImageAttachment({
  attachment,
  onRemove,
  uploadStatus,
}: {
  attachment: FileAttachment;
  onRemove: () => void;
  uploadStatus?: AttachmentUploadStatus;
}) {
  const { data: dataUrl } = useQuery({
    queryKey: ["os", "readFileAsDataUrl", attachment.id],
    queryFn: () => readFileAsDataUrl({ filePath: attachment.id }),
    staleTime: Infinity,
  });

  const [open, setOpen] = useState(false);
  const isGif = isGifFile(attachment.label);
  const canvasRef = useFrozenGif(dataUrl, isGif);
  const parsedImage = dataUrl ? parseImageDataUrl(dataUrl) : null;

  const preview = isGif ? (
    <canvas ref={canvasRef} aria-hidden className="size-full object-cover" />
  ) : dataUrl ? (
    <img src={dataUrl} alt="" className="size-full object-cover" />
  ) : (
    // Holds the square's shape until the data URL resolves.
    <span className="size-full bg-[var(--gray-a5)]" />
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Attachment
        label={attachment.label}
        preview={preview}
        hint="Click to preview"
        onOpen={() => setOpen(true)}
        onRemove={onRemove}
        status={uploadStatus}
      />
      <DialogContent className="w-fit max-w-[85vw]" showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{attachment.label}</DialogTitle>
        </DialogHeader>
        <DialogBody>
          {parsedImage ? (
            <SafeImagePreview
              base64={parsedImage.base64}
              mimeType={parsedImage.mimeType}
              alt={attachment.label}
              className="max-h-[75vh] max-w-[80vw]"
            />
          ) : (
            <Text size="sm" variant="muted">
              Unable to load image preview
            </Text>
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}

interface AttachmentsBarProps {
  attachments: FileAttachment[];
  onRemove: (id: string) => void;
  uploadStatuses?: Record<string, AttachmentUploadStatus>;
}

export function AttachmentsBar({
  attachments,
  onRemove,
  uploadStatuses,
}: AttachmentsBarProps) {
  if (attachments.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1">
      {attachments.map((att) =>
        isRasterImageFile(att.label) ? (
          <ImageAttachment
            key={att.id}
            attachment={att}
            onRemove={() => onRemove(att.id)}
            uploadStatus={uploadStatuses?.[att.id]}
          />
        ) : (
          <Attachment
            key={att.id}
            label={att.label}
            onRemove={() => onRemove(att.id)}
            status={uploadStatuses?.[att.id]}
          />
        ),
      )}
    </div>
  );
}
