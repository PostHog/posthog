import { isContentEmpty } from "@posthog/core/message-editor/content";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { persistImageFile } from "@posthog/ui/features/message-editor/utils/persistFile";
import { track } from "@posthog/ui/shell/analytics";
import {
  type CommentAgentContext,
  commentComposerContent,
} from "./commentAgentContext";
import { showTaskChat } from "./showTaskChat";

async function saveScreenshot(dataUrl: string): Promise<string | undefined> {
  try {
    const blob = await (await fetch(dataUrl)).blob();
    const file = new File([blob], "comment-screenshot.png", {
      type: blob.type || "image/png",
    });
    return (await persistImageFile(file)).path;
  } catch {
    return undefined;
  }
}

export async function sendCommentToAgent({
  taskId,
  comment,
  context,
  surface,
}: {
  taskId: string;
  comment: string;
  context: CommentAgentContext | null;
  surface: "preview" | "artifact" | "canvas" | "task";
}): Promise<void> {
  const imagePath = context?.screenshot
    ? await saveScreenshot(context.screenshot)
    : undefined;
  const actions = useDraftStore.getState().actions;
  actions.insertPendingContent(
    taskId,
    commentComposerContent({
      comment,
      draftEmpty: isContentEmpty(actions.getDraft(taskId)),
      context: context ? { ...context, imagePath } : null,
    }),
  );
  showTaskChat(taskId);
  actions.requestFocus(taskId);
  track(ANALYTICS_EVENTS.COMMENT_SENT_TO_AGENT, {
    surface,
    with_context: !!context,
    with_screenshot: !!imagePath,
  });
}
