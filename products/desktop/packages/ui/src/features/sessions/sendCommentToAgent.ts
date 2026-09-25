import { isContentEmpty } from "@posthog/core/message-editor/content";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { track } from "@posthog/ui/shell/analytics";
import {
  type CommentAgentContext,
  commentComposerContent,
} from "./commentAgentContext";
import { showTaskChat } from "./showTaskChat";

export function sendCommentToAgent({
  taskId,
  comment,
  context,
  surface,
}: {
  taskId: string;
  comment: string;
  context: CommentAgentContext | null;
  surface: "preview" | "artifact" | "canvas" | "task";
}): void {
  const actions = useDraftStore.getState().actions;
  actions.insertPendingContent(
    taskId,
    commentComposerContent({
      comment,
      draftEmpty: isContentEmpty(actions.getDraft(taskId)),
      context,
    }),
  );
  showTaskChat(taskId);
  actions.requestFocus(taskId);
  track(ANALYTICS_EVENTS.COMMENT_SENT_TO_AGENT, {
    surface,
    with_context: !!context,
  });
}
