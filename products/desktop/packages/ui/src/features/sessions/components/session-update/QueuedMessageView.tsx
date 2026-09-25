import {
  ArrowBendDownLeft,
  DotsSixVertical,
  PencilSimple,
  Trash,
  X,
} from "@phosphor-icons/react";
import { resolveMessageAttachments } from "@posthog/core/sessions/promptContent";
import { Button } from "@posthog/quill";
import { Box, Flex, IconButton, Text, Tooltip } from "@radix-ui/themes";
import clsx from "clsx";
import { type Ref, useMemo } from "react";
import { MarkdownRenderer } from "../../../editor/components/MarkdownRenderer";
import type { QueuedMessage } from "../../sessionStore";
import { UserMessageAttachments } from "../UserMessageAttachments";
import { CollapsibleMessageContent } from "./CollapsibleMessageContent";
import { hasFileMentions, parseFileMentions } from "./parseFileMentions";

interface QueuedMessageViewProps {
  message: QueuedMessage;
  dragHandleRef?: Ref<HTMLButtonElement>;
  onSteer?: () => void;
  onEdit?: () => void;
  onCancelEdit?: () => void;
  onRemove?: () => void;
  isEditing?: boolean;
  supportsNativeSteer?: boolean;
}

export function QueuedMessageView({
  message,
  dragHandleRef,
  onSteer,
  onEdit,
  onCancelEdit,
  onRemove,
  isEditing = false,
  supportsNativeSteer = false,
}: QueuedMessageViewProps) {
  const { text, attachments } = useMemo(
    () => resolveMessageAttachments(message.content, message.attachments ?? []),
    [message.content, message.attachments],
  );
  const steerTooltip = supportsNativeSteer
    ? "Inject this message into the current turn at the next tool boundary."
    : "Interrupt the current turn and resend with this message.";

  return (
    <Box
      className={clsx(
        "rounded-lg border px-3 py-2",
        isEditing
          ? "border-purple-8 bg-purple-2 ring-1 ring-purple-8"
          : "border-gray-5 bg-card",
      )}
    >
      {/* Pin the row height so it stays constant across states: the non-editing
          Steer button (fixed height) anchors it, but the editing state's ghost
          icon buttons are `fit-content` and would otherwise collapse shorter. */}
      <Flex align="center" gap="2" className="min-h-6">
        {dragHandleRef && (
          <button
            ref={dragHandleRef}
            type="button"
            aria-label="Drag to reorder"
            title="Drag to reorder"
            className="shrink-0 cursor-grab text-gray-9 hover:text-gray-11"
          >
            <DotsSixVertical size={14} aria-hidden />
          </button>
        )}
        <CollapsibleMessageContent
          className="min-w-0 flex-1"
          contentClassName="font-medium text-[13px] text-gray-12"
        >
          {attachments.length > 0 && (
            <div className={text ? "mb-1.5" : ""}>
              <UserMessageAttachments attachments={attachments} />
            </div>
          )}
          {hasFileMentions(text) ? (
            parseFileMentions(text)
          ) : (
            <MarkdownRenderer content={text} />
          )}
        </CollapsibleMessageContent>
        <Flex align="center" gap="2" className="shrink-0">
          {isEditing ? (
            <>
              <Text className="mr-1 text-[12px] text-purple-11">
                Editing in composer
              </Text>
              {onCancelEdit && (
                <Tooltip content="Cancel edit">
                  <IconButton
                    size="1"
                    variant="ghost"
                    color="gray"
                    aria-label="Cancel edit"
                    onClick={onCancelEdit}
                  >
                    <X size={12} />
                  </IconButton>
                </Tooltip>
              )}
            </>
          ) : (
            <>
              {onSteer && (
                <Tooltip content={steerTooltip}>
                  <Button
                    type="button"
                    variant="default"
                    size="sm"
                    aria-label="Steer this message"
                    onClick={onSteer}
                  >
                    <ArrowBendDownLeft size={12} />
                    <span>Steer</span>
                  </Button>
                </Tooltip>
              )}
              {onEdit && (
                <Tooltip content="Edit in composer">
                  <IconButton
                    size="1"
                    variant="ghost"
                    color="gray"
                    aria-label="Edit queued message"
                    onClick={onEdit}
                  >
                    <PencilSimple size={12} />
                  </IconButton>
                </Tooltip>
              )}
            </>
          )}
          {onRemove && (
            <Tooltip content="Discard">
              <IconButton
                size="1"
                variant="ghost"
                color="gray"
                aria-label="Discard queued message"
                onClick={onRemove}
              >
                <Trash size={12} />
              </IconButton>
            </Tooltip>
          )}
        </Flex>
      </Flex>
    </Box>
  );
}
