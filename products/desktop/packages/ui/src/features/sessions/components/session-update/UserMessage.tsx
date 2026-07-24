import {
  Check,
  Copy,
  FileText,
  Scroll,
  SlackLogo,
} from "@phosphor-icons/react";
import { PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import { Box, Flex, IconButton } from "@radix-ui/themes";
import { motion } from "framer-motion";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Tooltip } from "../../../../primitives/Tooltip";
import { MarkdownRenderer } from "../../../editor/components/MarkdownRenderer";
import { useFeatureFlag } from "../../../feature-flags/useFeatureFlag";
import { usePanelLayoutStore } from "../../../panels/panelLayoutStore";
import type { UserMessageAttachment } from "../../userMessageTypes";
import { UserMessageAttachments } from "../UserMessageAttachments";
import { CollapsibleMessageContent } from "./CollapsibleMessageContent";
import { extractCanvasInstructions } from "./canvasInstructions";
import { extractChannelContext } from "./channelContext";
import { extractCustomInstructions } from "./customInstructions";
import {
  hasFileMentions,
  MentionChip,
  parseFileMentions,
} from "./parseFileMentions";

interface UserMessageProps {
  content: string;
  timestamp?: number;
  sourceUrl?: string;
  attachments?: UserMessageAttachment[];
  animate?: boolean;
  /** Task the message belongs to — needed to open the context file tab. */
  taskId?: string;
  keyboardFocused?: boolean;
}

function formatTimestamp(ts: number): string {
  return new Date(ts).toLocaleString([], {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

// Rendered directly by the conversation's renderItem (no memoized wrapper, unlike
// agent messages which sit under SessionUpdateRow), so without memo every visible
// user message re-runs MarkdownRenderer on every parent render — and the
// virtualizer flushSync-renders on every scroll event. Props are referentially
// stable for completed turns (incremental parser), so memo skips them on scroll.
export const UserMessage = memo(function UserMessage({
  content,
  timestamp,
  sourceUrl,
  attachments = [],
  animate = true,
  taskId,
  keyboardFocused = false,
}: UserMessageProps) {
  // A channel's CONTEXT.md and the canvas generation instructions, if injected
  // into this prompt, are each collapsed into a clickable tag instead of
  // rendered inline; the rest of the prompt renders normally. Clicking a tag
  // opens the snapshot as a split tab. The clickable tag + split tab is a
  // project-bluebird feature, but we always strip the blocks so the raw
  // <channel_context>/<canvas_generation_instructions> XML never leaks for
  // flag-off viewers. The user's saved personalization
  // (<user_custom_instructions>) is always-on background, not contextual to this
  // message, so it's stripped without a tag.
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  const channelContext = useMemo(
    () => extractChannelContext(content),
    [content],
  );
  const afterChannelContext = channelContext
    ? channelContext.stripped
    : content;
  const canvasInstructions = useMemo(
    () => extractCanvasInstructions(afterChannelContext),
    [afterChannelContext],
  );
  const afterCanvasInstructions = canvasInstructions
    ? canvasInstructions.stripped
    : afterChannelContext;
  const customInstructions = useMemo(
    () => extractCustomInstructions(afterCanvasInstructions),
    [afterCanvasInstructions],
  );
  const displayContent = customInstructions
    ? customInstructions.stripped
    : afterCanvasInstructions;
  const showChannelContextTag = !!channelContext && bluebirdEnabled;
  const showCanvasInstructionsTag = !!canvasInstructions && bluebirdEnabled;
  const openChannelContextInSplit = usePanelLayoutStore(
    (s) => s.openChannelContextInSplit,
  );
  const openCanvasInstructionsInSplit = usePanelLayoutStore(
    (s) => s.openCanvasInstructionsInSplit,
  );

  const containsFileMentions = hasFileMentions(displayContent);
  const showAttachmentChips = attachments.length > 0 && !containsFileMentions;
  const [copied, setCopied] = useState(false);

  const copiedTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    return () => clearTimeout(copiedTimerRef.current);
  }, []);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(displayContent);
    setCopied(true);
    clearTimeout(copiedTimerRef.current);
    copiedTimerRef.current = setTimeout(() => setCopied(false), 2000);
  }, [displayContent]);

  return (
    <motion.div
      initial={animate ? { opacity: 0, y: 6 } : false}
      animate={{ opacity: 1, y: 0 }}
      transition={animate ? { duration: 0.25, ease: "easeOut" } : undefined}
    >
      <Box
        className={`group/msg relative border-l-2 bg-gray-2 py-2 pl-3 transition-shadow ${keyboardFocused ? "ring-(--accent-9) ring-2 ring-offset-(--gray-2) ring-offset-2" : ""}`}
        style={{ borderColor: "var(--accent-9)" }}
      >
        <CollapsibleMessageContent contentClassName="font-medium text-[13px] [&_p]:leading-[1.9]">
          {containsFileMentions ? (
            parseFileMentions(displayContent)
          ) : (
            <MarkdownRenderer content={displayContent} />
          )}
          {(showChannelContextTag || showCanvasInstructionsTag) && (
            <Flex
              wrap="wrap"
              gap="1"
              className={displayContent ? "mt-1.5" : ""}
            >
              {showChannelContextTag && channelContext && (
                <MentionChip
                  icon={<FileText size={12} />}
                  label={`${
                    channelContext.mention.name
                      ? `#${channelContext.mention.name} `
                      : ""
                  }CONTEXT.md`}
                  onClick={
                    taskId
                      ? () =>
                          openChannelContextInSplit(taskId, {
                            channelName: channelContext.mention.name,
                            body: channelContext.mention.body,
                          })
                      : undefined
                  }
                />
              )}
              {showCanvasInstructionsTag && canvasInstructions && (
                <MentionChip
                  icon={<Scroll size={12} />}
                  label="Canvas instructions"
                  onClick={
                    taskId
                      ? () =>
                          openCanvasInstructionsInSplit(taskId, {
                            body: canvasInstructions.body,
                          })
                      : undefined
                  }
                />
              )}
            </Flex>
          )}
          {showAttachmentChips && (
            <div className={content.trim() ? "mt-1.5" : ""}>
              <UserMessageAttachments attachments={attachments} />
            </div>
          )}
        </CollapsibleMessageContent>
        {sourceUrl && (
          <a
            href={sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1.5 inline-flex items-center gap-1 text-[12px] text-gray-10 transition-colors hover:text-gray-12"
          >
            <SlackLogo size={12} />
            <span>View Slack thread</span>
          </a>
        )}
        <Box className="absolute top-1 right-1 flex select-none items-center gap-1.5 rounded-md bg-gray-2 py-0.5 pr-1 pl-2 opacity-0 shadow-sm transition-opacity group-hover/msg:opacity-100">
          {timestamp != null && (
            <span aria-hidden className="text-[11px] text-gray-10">
              {formatTimestamp(timestamp)}
            </span>
          )}
          <Tooltip content={copied ? "Copied!" : "Copy message"}>
            <IconButton
              size="1"
              variant="ghost"
              color={copied ? "green" : "gray"}
              onClick={handleCopy}
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
            </IconButton>
          </Tooltip>
        </Box>
      </Box>
    </motion.div>
  );
});
