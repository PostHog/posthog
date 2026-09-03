import { CaretDown } from "@phosphor-icons/react";
import { cn } from "@posthog/quill";
import { ChatMarkdown } from "@posthog/ui/features/sessions/components/chat-thread/ChatMarkdown";
import {
  hasFileMentions,
  parseFileMentions,
} from "@posthog/ui/features/sessions/components/session-update/parseFileMentions";
import { UserMessageAttachments } from "@posthog/ui/features/sessions/components/UserMessageAttachments";
import type { UserMessageAttachment } from "@posthog/ui/features/sessions/userMessageTypes";
import { useEffect, useRef, useState } from "react";

/**
 * The body of a user-authored chat bubble. Content carrying file, folder,
 * GitHub, or slash-command mentions renders as chips, so the same prompt draws
 * identically in the live transcript and in views that precede it. Plain
 * content renders as markdown.
 *
 * Attachments hide when the content carries file mentions: contentToXml folds
 * every attachment into a <file /> tag, so showing both would list it twice.
 *
 * Long content clamps to five lines with a Show more toggle, so a bubble in a
 * pre-transcript view never grows past what the live bubble would show.
 */
export function UserMessageBody({
  content,
  attachments = [],
}: {
  content: string;
  attachments?: UserMessageAttachment[];
}) {
  const containsFileMentions = hasFileMentions(content);

  const [isExpanded, setIsExpanded] = useState(false);
  const [isOverflowing, setIsOverflowing] = useState(false);
  const textRef = useRef<HTMLDivElement>(null);

  // Only meaningful while collapsed: expanding removes the clamp so scrollHeight === clientHeight.
  // We keep the prior result when expanded so the "Show less" trigger stays put.
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-measure when the message text changes.
  useEffect(() => {
    if (isExpanded) return;
    const el = textRef.current;
    if (!el) return;
    // The observer fires once on observe, after layout, so the first measure
    // forces no layout inside the commit.
    const observer = new ResizeObserver(() =>
      setIsOverflowing(el.scrollHeight - el.clientHeight > 1),
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [content, isExpanded]);

  return (
    <>
      <div
        ref={textRef}
        className={cn(
          "[&_p]:my-0",
          !isExpanded && "max-h-[5lh] overflow-hidden",
          // Fade the clamped text out at the bottom so it reads as "continues below". Only
          // when actually overflowing — a short collapsed message shouldn't fade. The mask is
          // paint-only, so it doesn't affect the overflow measurement above.
          !isExpanded &&
            isOverflowing &&
            "[mask-image:linear-gradient(to_bottom,black_45%,transparent)]",
        )}
      >
        {containsFileMentions ? (
          parseFileMentions(content)
        ) : (
          <ChatMarkdown content={content} />
        )}
      </div>
      {attachments.length > 0 && !containsFileMentions && (
        <div className="mt-1.5">
          <UserMessageAttachments attachments={attachments} />
        </div>
      )}
      {isOverflowing && (
        <button
          type="button"
          onClick={() => setIsExpanded((v) => !v)}
          className="mt-1 flex items-center gap-0.5 text-muted-foreground text-sm hover:text-foreground"
        >
          Show {isExpanded ? "less" : "more"}
          <CaretDown className={cn("size-3", isExpanded && "rotate-180")} />
        </button>
      )}
    </>
  );
}
