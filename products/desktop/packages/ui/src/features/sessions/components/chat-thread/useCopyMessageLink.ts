import { useSessionTaskId } from "@posthog/ui/features/sessions/useSessionTaskId";
import { toast } from "@posthog/ui/primitives/toast";
import { useCopy } from "@posthog/ui/primitives/useCopy";
import { taskShareUrl } from "@posthog/ui/utils/posthogLinks";
import { useCallback } from "react";

/**
 * Copies the shareable link that reopens this transcript scrolled to one message. Backs both link
 * affordances in the thread — the minimap's per-message icon and the turn footer's — so they copy
 * the same url and report the same state.
 *
 * `copyLink` is null when the thread has no task behind it (the live-agent preview), because there
 * is nothing for a link to reopen. Callers render nothing in that case rather than a button that
 * cannot work.
 */
export function useCopyMessageLink(messageId: string): {
  copied: boolean;
  copyLink: (() => void) | null;
} {
  const taskId = useSessionTaskId();
  const { copied, copy } = useCopy();

  const copyLink = useCallback(() => {
    const url = taskId ? taskShareUrl(taskId, messageId) : null;
    if (!url) {
      // No signed-in region to build an instance url against. Say so — a silent no-op would
      // leave the reader pasting whatever the clipboard already held.
      toast.error("Couldn't build a link to this message");
      return;
    }
    copy(url);
  }, [copy, messageId, taskId]);

  return { copied, copyLink: taskId ? copyLink : null };
}
