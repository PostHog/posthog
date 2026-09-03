import { ChatMarkdown } from "@posthog/ui/features/sessions/components/chat-thread/ChatMarkdown";
import {
  hasFileMentions,
  parseFileMentions,
} from "@posthog/ui/features/sessions/components/session-update/parseFileMentions";
import { UserMessageAttachments } from "@posthog/ui/features/sessions/components/UserMessageAttachments";
import type { UserMessageAttachment } from "@posthog/ui/features/sessions/userMessageTypes";

/**
 * The body of a user-authored chat bubble. Content carrying file, folder,
 * GitHub, or slash-command mentions renders as chips, so the same prompt draws
 * identically in the live transcript and in views that precede it. Plain
 * content renders as markdown.
 *
 * Attachments hide when the content carries file mentions: contentToXml folds
 * every attachment into a <file /> tag, so showing both would list it twice.
 */
export function UserMessageBody({
  content,
  attachments = [],
}: {
  content: string;
  attachments?: UserMessageAttachment[];
}) {
  const containsFileMentions = hasFileMentions(content);
  return (
    <>
      {containsFileMentions ? (
        parseFileMentions(content)
      ) : (
        <ChatMarkdown content={content} />
      )}
      {attachments.length > 0 && !containsFileMentions && (
        <div className="mt-1.5">
          <UserMessageAttachments attachments={attachments} />
        </div>
      )}
    </>
  );
}
