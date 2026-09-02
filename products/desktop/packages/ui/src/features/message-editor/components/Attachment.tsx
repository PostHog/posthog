import { FileIcon, WarningCircle, X } from "@phosphor-icons/react";
import {
  Button,
  cn,
  Spinner,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { fileExtensionLabel } from "@posthog/ui/features/message-editor/fileKind";
import type { ReactNode } from "react";

export type AttachmentUploadStatus = "uploading" | "error";

/**
 * Extensions that read better as their own mark than as text. ".JSON" is five
 * characters crammed into a 32px square; "{}" is the same idea at a glance.
 */
const EXTENSION_GLYPHS: Record<string, string> = {
  ".json": "{}",
};

/**
 * One attachment on a prompt: a square the size of the composer's other icon
 * buttons, showing the file's own picture when it has one and a document glyph
 * when it doesn't. The filename lives in the tooltip rather than beside the
 * square — across a row of these, names cost more room than they buy.
 */
export function Attachment({
  label,
  preview,
  hint,
  onOpen,
  onRemove,
  status,
}: {
  label: string;
  /**
   * The file's own thumbnail. Without one the square shows the extension, which
   * says more at this size than a generic document glyph does.
   */
  preview?: ReactNode;
  /** Second tooltip line: what clicking the square does. Omit when nothing does. */
  hint?: string;
  onOpen?: () => void;
  onRemove?: () => void;
  status?: AttachmentUploadStatus;
}) {
  const extension = fileExtensionLabel(label);
  const glyph = extension ? EXTENSION_GLYPHS[extension] : undefined;
  const face =
    preview ??
    (glyph ? (
      <span className="font-medium font-mono text-[13px]">{glyph}</span>
    ) : extension ? (
      <span className="font-medium text-[10px] uppercase">{extension}</span>
    ) : (
      <FileIcon size={16} weight="duotone" />
    ));

  return (
    // The remove control is a badge over the corner rather than a slot inside,
    // so it costs the square no room. Keyboard focus reveals it too — hover
    // alone would strand it.
    // Hovering lifts the whole attachment above its neighbours so the remove
    // badge, which overhangs the corner, isn't clipped under the next square.
    <div className="group/attachment relative shrink-0 focus-within:z-10 hover:z-10">
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              type="button"
              variant="outline"
              size="icon-lg"
              aria-label={label}
              onClick={onOpen}
              // Explicit square: `icon-lg` sizes the box, but a thumbnail is
              // free to stretch a flex button, so the face is absolutely
              // positioned inside a fixed one instead.
              className={cn(
                "relative size-8 shrink-0 overflow-hidden p-0",
                !onOpen && "cursor-default",
              )}
            >
              <span className="absolute inset-0 flex items-center justify-center">
                {face}
              </span>
              {status && (
                <span className="absolute inset-0 flex items-center justify-center bg-[var(--gray-a5)]">
                  {status === "uploading" ? (
                    <Spinner
                      className="size-3.5"
                      aria-label="Uploading attachment"
                    />
                  ) : (
                    <WarningCircle
                      size={14}
                      className="text-red-9"
                      aria-label="Attachment upload failed"
                    />
                  )}
                </span>
              )}
            </Button>
          }
        />
        <TooltipContent side="top">
          {label}
          {hint && (
            <>
              <br />
              {hint}
            </>
          )}
        </TooltipContent>
      </Tooltip>
      {onRemove && (
        <button
          type="button"
          aria-label={`Remove ${label}`}
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="-top-1.5 -right-1.5 absolute z-10 flex size-4 items-center justify-center rounded-full bg-gray-9 text-gray-1 opacity-0 shadow-sm transition-opacity hover:bg-gray-10 focus-visible:opacity-100 group-focus-within/attachment:opacity-100 group-hover/attachment:opacity-100 motion-reduce:transition-none"
        >
          <X size={9} weight="bold" />
        </button>
      )}
    </div>
  );
}
