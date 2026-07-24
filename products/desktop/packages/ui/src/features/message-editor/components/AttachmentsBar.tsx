import { File, X } from "@phosphor-icons/react";
import type { FileAttachment } from "@posthog/core/message-editor/content";
import {
  isGifFile,
  isRasterImageFile,
  parseImageDataUrl,
} from "@posthog/shared";
import { SafeImagePreview } from "@posthog/ui/primitives/SafeImagePreview";
import { Dialog, Flex, IconButton, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { readFileAsDataUrl } from "../hostApi";

function FrozenGifThumbnail({ src, alt }: { src: string; alt: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const img = new Image();
    img.onload = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const size = 56;
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
  }, [src]);

  return (
    <canvas ref={canvasRef} aria-label={alt} className="size-3.5 rounded-sm" />
  );
}

function ImageThumbnail({
  attachment,
  onRemove,
}: {
  attachment: FileAttachment;
  onRemove: () => void;
}) {
  const { data: dataUrl } = useQuery({
    queryKey: ["os", "readFileAsDataUrl", attachment.id],
    queryFn: () => readFileAsDataUrl({ filePath: attachment.id }),
    staleTime: Infinity,
  });

  const isGif = isGifFile(attachment.label);
  const parsedImage = dataUrl ? parseImageDataUrl(dataUrl) : null;

  return (
    <Dialog.Root>
      <div className="group relative flex-shrink-0">
        <Dialog.Trigger>
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-[var(--radius-1)] bg-[var(--gray-a3)] p-1 font-medium text-[11px] text-[var(--gray-11)] hover:bg-[var(--gray-a4)]"
          >
            {dataUrl ? (
              isGif ? (
                <FrozenGifThumbnail src={dataUrl} alt={attachment.label} />
              ) : (
                <img
                  src={dataUrl}
                  alt={attachment.label}
                  className="size-3.5 rounded-sm object-cover"
                />
              )
            ) : (
              <span className="size-3.5 rounded-sm bg-[var(--gray-a5)]" />
            )}
            <span className="max-w-[80px] truncate">{attachment.label}</span>
          </button>
        </Dialog.Trigger>
        <IconButton
          size="1"
          variant="solid"
          color="gray"
          className="!absolute -top-1 -right-1 !size-3.5 opacity-0 transition-opacity group-hover:opacity-100"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
        >
          <X size={8} weight="bold" />
        </IconButton>
      </div>
      <Dialog.Content maxWidth="85vw" className="w-fit p-[16px]">
        <Dialog.Title mb="2" className="text-sm">
          {attachment.label}
        </Dialog.Title>
        {parsedImage ? (
          <SafeImagePreview
            base64={parsedImage.base64}
            mimeType={parsedImage.mimeType}
            alt={attachment.label}
            className="max-h-[75vh] max-w-[80vw]"
          />
        ) : (
          <Text color="gray" className="text-sm">
            Unable to load image preview
          </Text>
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}

function FileChip({
  attachment,
  onRemove,
}: {
  attachment: FileAttachment;
  onRemove: () => void;
}) {
  return (
    <span className="group/chip inline-flex flex-shrink-0 items-center gap-1 rounded-[var(--radius-1)] bg-[var(--gray-a3)] p-1 font-medium text-[11px] text-[var(--gray-11)]">
      <button
        type="button"
        tabIndex={-1}
        aria-label="Remove attachment"
        className="relative inline-flex size-3.5 shrink-0 cursor-pointer items-center justify-center border-none bg-transparent p-0"
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
      >
        <span className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-100 transition-opacity duration-150 group-hover/chip:opacity-0 motion-reduce:transition-none">
          <File size={14} weight="duotone" />
        </span>
        <span className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-0 transition-opacity duration-150 group-hover/chip:opacity-100 motion-reduce:transition-none">
          <X size={12} weight="bold" />
        </span>
      </button>
      <span className="max-w-[120px] truncate">{attachment.label}</span>
    </span>
  );
}

interface AttachmentsBarProps {
  attachments: FileAttachment[];
  onRemove: (id: string) => void;
}

export function AttachmentsBar({ attachments, onRemove }: AttachmentsBarProps) {
  if (attachments.length === 0) return null;

  return (
    <Flex gap="1" align="center" className="flex-wrap pb-1.5">
      {attachments.map((att) =>
        isRasterImageFile(att.label) ? (
          <ImageThumbnail
            key={att.id}
            attachment={att}
            onRemove={() => onRemove(att.id)}
          />
        ) : (
          <FileChip
            key={att.id}
            attachment={att}
            onRemove={() => onRemove(att.id)}
          />
        ),
      )}
    </Flex>
  );
}
