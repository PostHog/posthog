import {
  ArrowCounterClockwise,
  CaretDown,
  CaretRight,
  CaretUp,
  ChatCircle,
  CheckCircle,
  File,
  Robot,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import {
  buildAskAboutPrCommentPrompt,
  buildChatAboutPrCommentPrompt,
  buildFixPrCommentPrompt,
} from "@posthog/core/code-review/reviewPrompts";
import { Button } from "@posthog/quill";
import type { PrReviewComment } from "@posthog/shared";
import { formatRelativeTimeShort } from "@posthog/shared";
import { Avatar, Badge, Box, Flex, Text } from "@radix-ui/themes";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import type { PluggableList } from "unified";
import { isSendMessageSubmitKey } from "../../../utils/sendMessageKey";
import { MarkdownRenderer } from "../../editor/components/MarkdownRenderer";
import { sendPromptToAgent } from "../../sessions/sendPromptToAgent";
import { usePrCommentActions } from "../hooks/usePrCommentActions";
import type { PrCommentMetadata } from "../types";

const ghRehypePlugins: PluggableList = [
  rehypeRaw,
  [rehypeSanitize, defaultSchema],
];

const MAX_COMMENT_HEIGHT = 120;
type ComposerMode = "reply" | "chat";

/** Strip markdown noise to a single-line preview for the collapsed header. */
function toPreview(body: string): string {
  return body
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/<[^>]*>/g, " ")
    .replace(/[#>*_`~-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

interface ThreadActionBarProps {
  prUrl: string | null;
  taskId: string;
  filePath: string;
  endLine: number;
  side: "old" | "new";
  comments: PrReviewComment[];
  isResolved: boolean;
  onResolveToggle: () => void;
  composerMode: ComposerMode | null;
  pendingReply: string | null;
  isSendingChat: boolean;
  onShowComposer: (mode: ComposerMode) => void;
  onHideComposer: () => void;
  onSubmitComposer: () => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  textareaRefCallback: (el: HTMLTextAreaElement | null) => void;
}

function ThreadActionBar({
  prUrl,
  taskId,
  filePath,
  endLine,
  side,
  comments,
  isResolved,
  onResolveToggle,
  composerMode,
  pendingReply,
  isSendingChat,
  onShowComposer,
  onHideComposer,
  onSubmitComposer,
  onKeyDown,
  textareaRefCallback,
}: ThreadActionBarProps) {
  if (composerMode) {
    const isReply = composerMode === "reply";
    const isSending = isSendingChat || (isReply && !!pendingReply);
    const submitLabel = isSending ? "Sending..." : isReply ? "Reply" : "Send";
    return (
      <div className="mt-1.5 border-[var(--gray-4)] border-t pt-1.5">
        <textarea
          ref={textareaRefCallback}
          placeholder={
            isReply ? "Write a reply..." : "Ask the agent about this comment..."
          }
          onKeyDown={onKeyDown}
          className="min-h-[48px] w-full resize-none rounded border border-[var(--gray-6)] bg-[var(--color-background)] p-1.5 text-[13px] text-[var(--gray-12)] leading-normal outline-none"
        />
        <Flex align="center" gap="2" className="mt-1.5">
          <Button
            variant="primary"
            size="sm"
            onClick={onSubmitComposer}
            disabled={isSending}
          >
            {isReply ? <ChatCircle /> : <Robot />}
            {submitLabel}
          </Button>
          <Button
            size="icon-sm"
            aria-label="Close composer"
            onClick={onHideComposer}
          >
            <X />
          </Button>
        </Flex>
      </div>
    );
  }

  return (
    <Flex
      align="center"
      gap="1"
      className="mt-1 border-[var(--gray-4)] border-t pt-1.5"
    >
      {prUrl && (
        <Button size="sm" onClick={() => onShowComposer("reply")}>
          <ChatCircle />
          Reply
        </Button>
      )}

      {prUrl && (
        <Button size="sm" onClick={onResolveToggle}>
          {isResolved ? (
            <>
              <ArrowCounterClockwise />
              Unresolve
            </>
          ) : (
            <>
              <CheckCircle />
              Resolve
            </>
          )}
        </Button>
      )}

      <Button
        size="sm"
        onClick={() =>
          sendPromptToAgent(
            taskId,
            buildFixPrCommentPrompt(filePath, endLine, side, comments),
          )
        }
      >
        <Robot />
        Fix
      </Button>

      <Button
        size="sm"
        onClick={() =>
          sendPromptToAgent(
            taskId,
            buildAskAboutPrCommentPrompt(filePath, endLine, side, comments),
          )
        }
      >
        <Robot />
        Ask
      </Button>

      <Button size="sm" onClick={() => onShowComposer("chat")}>
        <Robot />
        Chat
      </Button>
    </Flex>
  );
}

interface PrCommentThreadProps {
  taskId: string;
  prUrl: string | null;
  filePath: string;
  metadata: PrCommentMetadata;
}

function CommentBody({
  comment,
  showLineAbove = false,
  showLineBelow = false,
  badges,
}: {
  comment: PrReviewComment;
  showLineAbove?: boolean;
  showLineBelow?: boolean;
  badges?: ReactNode;
}) {
  const contentRef = useRef<HTMLDivElement>(null);
  const [isOverflowing, setIsOverflowing] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);

  useEffect(() => {
    const el = contentRef.current;
    if (el) {
      setIsOverflowing(el.scrollHeight > MAX_COMMENT_HEIGHT);
    }
  }, []);

  return (
    <div className="flex gap-2">
      <div className="flex flex-col items-center">
        {showLineAbove ? (
          <div className="h-1.5 w-0.5 rounded-full bg-[var(--gray-5)]" />
        ) : (
          <div className="h-1.5" />
        )}
        <Avatar
          size="1"
          radius="full"
          src={comment.user.avatar_url}
          fallback={comment.user.login[0]?.toUpperCase() ?? "?"}
          className="shrink-0"
        />
        {showLineBelow && (
          <div className="w-0.5 flex-1 rounded-full bg-[var(--gray-5)]" />
        )}
      </div>
      <div className="min-w-0 flex-1 pt-1.5 pb-1.5">
        <Flex align="center" gap="2" className="mb-0.5">
          <Text className="font-medium text-[13px] text-[var(--gray-12)]">
            {comment.user.login}
          </Text>
          <Text className="text-[13px] text-[var(--gray-9)]">
            {formatRelativeTimeShort(comment.created_at)}
          </Text>
          {badges}
        </Flex>
        <Box
          ref={contentRef}
          className="relative overflow-hidden break-words text-[13px] text-[var(--gray-11)] leading-relaxed [&_code]:break-all [&_img]:max-w-full [&_p]:m-0 [&_pre]:max-w-full [&_pre]:overflow-x-auto"
          style={{
            maxHeight:
              isExpanded || !isOverflowing
                ? undefined
                : `${MAX_COMMENT_HEIGHT}px`,
            overflowWrap: "break-word",
          }}
        >
          <MarkdownRenderer
            content={comment.body}
            rehypePlugins={ghRehypePlugins}
          />
          {!isExpanded && isOverflowing && (
            <Box
              className="pointer-events-none absolute inset-x-0 bottom-0 h-12"
              style={{
                background: "linear-gradient(transparent, var(--gray-2))",
              }}
            />
          )}
        </Box>
        {isOverflowing && (
          <Button
            size="sm"
            onClick={() => setIsExpanded((prev) => !prev)}
            className="mt-1"
          >
            {isExpanded ? (
              <>
                <CaretUp />
                Show less
              </>
            ) : (
              <>
                <CaretDown />
                Show more
              </>
            )}
          </Button>
        )}
      </div>
    </div>
  );
}

export function PrCommentThread({
  taskId,
  prUrl,
  filePath,
  metadata,
}: PrCommentThreadProps) {
  const {
    threadId,
    nodeId,
    isResolved: initialIsResolved,
    comments,
    isOutdated,
    isFileLevel,
    endLine,
    side: annotationSide,
  } = metadata;
  const side = annotationSide === "deletions" ? "old" : "new";
  const { reply, resolve } = usePrCommentActions(prUrl);
  const [composerMode, setComposerMode] = useState<ComposerMode | null>(null);
  const [pendingReply, setPendingReply] = useState<string | null>(null);
  const [isSendingChat, setIsSendingChat] = useState(false);
  const [isResolved, setIsResolved] = useState(initialIsResolved);
  // Resolved/outdated threads add up — start them collapsed.
  const [isCollapsed, setIsCollapsed] = useState(
    initialIsResolved || isOutdated,
  );
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    setIsResolved(initialIsResolved);
  }, [initialIsResolved]);

  // Clear pending reply once the real comments list includes it
  const lastCommentId = comments[comments.length - 1]?.id;
  const prevLastCommentIdRef = useRef(lastCommentId);
  useEffect(() => {
    if (lastCommentId !== prevLastCommentIdRef.current && pendingReply) {
      setPendingReply(null);
    }
    prevLastCommentIdRef.current = lastCommentId;
  }, [lastCommentId, pendingReply]);

  const handleComposerSubmit = useCallback(async () => {
    const text = textareaRef.current?.value?.trim();
    if (!text || !composerMode) return;

    if (composerMode === "chat") {
      setIsSendingChat(true);
      const success = await sendPromptToAgent(
        taskId,
        buildChatAboutPrCommentPrompt(filePath, endLine, side, comments, text),
      );
      setIsSendingChat(false);
      if (success) {
        setComposerMode((currentMode) =>
          currentMode === "chat" ? null : currentMode,
        );
      }
      return;
    }

    setPendingReply(text);
    setComposerMode(null);
    const success = await reply(threadId, text);
    if (!success) {
      setPendingReply(null);
    }
  }, [
    comments,
    composerMode,
    endLine,
    filePath,
    reply,
    side,
    taskId,
    threadId,
  ]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (isSendMessageSubmitKey(e)) {
        e.preventDefault();
        handleComposerSubmit();
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setComposerMode(null);
      }
    },
    [handleComposerSubmit],
  );

  const setTextareaRefCallback = useCallback(
    (el: HTMLTextAreaElement | null) => {
      textareaRef.current = el;
      if (el) {
        requestAnimationFrame(() => el.focus());
      }
    },
    [],
  );

  const handleResolveToggle = useCallback(async () => {
    const next = !isResolved;
    setIsResolved(next);
    const success = await resolve(nodeId, next);
    if (!success) setIsResolved(!next);
  }, [isResolved, nodeId, resolve]);

  const toggleCollapsed = useCallback(
    () => setIsCollapsed((prev) => !prev),
    [],
  );

  const badges = (
    <>
      {isResolved && (
        <Badge color="green" size="1" variant="soft">
          <CheckCircle size={12} weight="fill" />
          Resolved
        </Badge>
      )}
      {isFileLevel && (
        <Badge color="gray" size="1" variant="soft">
          <File size={12} />
          File comment
        </Badge>
      )}
      {isOutdated && (
        <Badge color="yellow" size="1" variant="soft">
          <WarningCircle size={12} weight="fill" />
          Outdated
        </Badge>
      )}
    </>
  );

  return (
    <div className="px-3 py-1.5" style={{ contain: "inline-size" }}>
      <div
        data-pr-comment-thread=""
        className={`overflow-hidden whitespace-normal rounded-md border border-[var(--gray-5)] bg-[var(--gray-2)] px-2.5 py-2 font-sans ${isResolved ? "opacity-60" : ""}`}
      >
        <div className="flex gap-1">
          {/* Caret lives in a fixed gutter so it stays put when toggling. */}
          <div className="shrink-0 pt-2.5">
            <button
              type="button"
              onClick={toggleCollapsed}
              aria-label={isCollapsed ? "Expand thread" : "Collapse thread"}
              className="-ml-0.5 before:-inset-2 relative flex shrink-0 cursor-pointer items-center rounded p-0.5 text-[var(--gray-10)] transition-colors before:absolute before:content-[''] hover:bg-[var(--gray-4)] hover:text-[var(--gray-12)]"
            >
              <CaretRight
                size={14}
                className={`transition-transform duration-200 ${
                  isCollapsed ? "" : "rotate-90"
                }`}
              />
            </button>
          </div>

          <div className="min-w-0 flex-1">
            {isCollapsed && (
              <button
                type="button"
                onClick={toggleCollapsed}
                className="flex w-full min-w-0 cursor-pointer items-center gap-1.5 py-1.5 text-left"
              >
                {badges}
                <Text className="shrink-0 font-medium text-[13px] text-[var(--gray-12)]">
                  {comments[0]?.user.login}
                </Text>
                <Text className="min-w-0 flex-1 truncate text-[13px] text-[var(--gray-10)]">
                  {toPreview(comments[0]?.body ?? "")}
                </Text>
                {comments.length > 1 && (
                  <Badge
                    color="gray"
                    size="1"
                    variant="soft"
                    className="shrink-0"
                  >
                    <ChatCircle size={11} />
                    {comments.length}
                  </Badge>
                )}
              </button>
            )}

            {/* Grid-rows trick animates the body height open/closed smoothly. */}
            <div
              className={`grid transition-[grid-template-rows] duration-200 ease-out ${
                isCollapsed ? "grid-rows-[0fr]" : "grid-rows-[1fr]"
              }`}
            >
              <div className="overflow-hidden">
                {comments.map((comment, index) => (
                  <CommentBody
                    key={comment.id}
                    comment={comment}
                    showLineAbove={index > 0}
                    showLineBelow={
                      index < comments.length - 1 || !!pendingReply
                    }
                    badges={index === 0 ? badges : undefined}
                  />
                ))}

                {pendingReply && (
                  <div className="flex gap-2 opacity-50">
                    <div className="flex flex-col items-center">
                      <div className="h-1.5 w-0.5 rounded-full bg-[var(--gray-5)]" />
                      <Avatar
                        size="1"
                        radius="full"
                        fallback=""
                        className="shrink-0"
                      />
                    </div>
                    <div className="min-w-0 flex-1 pt-1.5 pb-1.5">
                      <Flex align="center" gap="2" className="mb-0.5">
                        <Text className="font-medium text-[13px] text-[var(--gray-12)]">
                          Sending...
                        </Text>
                      </Flex>
                      <div className="text-[13px] text-[var(--gray-11)] leading-relaxed">
                        <MarkdownRenderer
                          content={pendingReply}
                          rehypePlugins={ghRehypePlugins}
                        />
                      </div>
                    </div>
                  </div>
                )}

                <ThreadActionBar
                  prUrl={prUrl}
                  taskId={taskId}
                  filePath={filePath}
                  endLine={endLine}
                  side={side}
                  comments={comments}
                  isResolved={isResolved}
                  onResolveToggle={handleResolveToggle}
                  composerMode={composerMode}
                  pendingReply={pendingReply}
                  isSendingChat={isSendingChat}
                  onShowComposer={setComposerMode}
                  onHideComposer={() => setComposerMode(null)}
                  onSubmitComposer={handleComposerSubmit}
                  onKeyDown={handleKeyDown}
                  textareaRefCallback={setTextareaRefCallback}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
