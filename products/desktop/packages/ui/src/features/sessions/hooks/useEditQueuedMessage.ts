import {
  type EditorContent,
  isContentEmpty,
  textToContent,
  xmlToContent,
} from "@posthog/core/message-editor/content";
import {
  combineQueuedCloudPrompts,
  promptToQueuedEditorContent,
} from "@posthog/core/sessions/cloudPrompt";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import {
  type QueuedMessage,
  useSessionIsCloud,
} from "@posthog/ui/features/sessions/sessionStore";
import { useCallback } from "react";

/**
 * Empty editor content, used to clear the composer when a cancelled edit has no
 * prior draft to restore.
 */
const EMPTY_CONTENT: EditorContent = { segments: [] };

/**
 * Load a queued message back into the composer for editing while keeping it in
 * the queue at its current position. Marks the message as the active edit
 * target so the composer's next submit updates it in place (see
 * `useSessionCallbacks.handleSendPrompt`) rather than sending a new prompt.
 *
 * Snapshots whatever the user already had in the composer before overwriting it
 * with the queued message, so cancelling the edit restores that draft rather
 * than blanking it (see `useCancelQueuedMessageEdit`).
 *
 * Content restore mirrors the cancel-to-composer path: cloud keeps its rich
 * payload (mentions, attachments) via the queued-cloud conversion; local
 * restores the serialized text (chips reparse from the `<file .../>` tags).
 */
export function useEditQueuedMessage(
  taskId: string | undefined,
): (message: QueuedMessage) => void {
  const { requestFocus, setPendingContent, setPreEditDraft, getDraft } =
    useDraftStore((s) => s.actions);
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const isCloud = useSessionIsCloud(taskId);

  return useCallback(
    (message: QueuedMessage) => {
      if (!taskId) return;

      let pendingContent: EditorContent | null;
      if (isCloud) {
        const combined = combineQueuedCloudPrompts([message]);
        pendingContent = combined
          ? promptToQueuedEditorContent(combined)
          : null;
      } else {
        pendingContent = xmlToContent(message.content);
      }
      if (!pendingContent) return;

      // Capture the current composer draft before the queued message overwrites
      // it, so a cancelled edit can put it back. Normalize the legacy string
      // form to editor content; an empty draft snapshots as nothing to restore.
      const priorDraft = getDraft(taskId);
      setPreEditDraft(
        taskId,
        !priorDraft || isContentEmpty(priorDraft)
          ? null
          : typeof priorDraft === "string"
            ? textToContent(priorDraft)
            : priorDraft,
      );

      sessionService.setEditingQueuedMessage(taskId, message.id);
      setPendingContent(taskId, pendingContent);
      requestFocus(taskId);
    },
    [
      taskId,
      isCloud,
      requestFocus,
      setPendingContent,
      setPreEditDraft,
      getDraft,
      sessionService,
    ],
  );
}

/**
 * Abandon an in-progress queued-message edit: drop the edit target so the next
 * submit sends normally again, and restore the draft that was in the composer
 * before the edit began (blanking it only when there was none), so cancelling
 * never discards unrelated work the user had typed.
 */
export function useCancelQueuedMessageEdit(
  taskId: string | undefined,
): () => void {
  const { setPendingContent, takePreEditDraft } = useDraftStore(
    (s) => s.actions,
  );
  const sessionService = useService<SessionService>(SESSION_SERVICE);

  return useCallback(() => {
    if (!taskId) return;
    sessionService.clearEditingQueuedMessage(taskId);
    setPendingContent(taskId, takePreEditDraft(taskId) ?? EMPTY_CONTENT);
  }, [taskId, sessionService, setPendingContent, takePreEditDraft]);
}
