import type { CommentToAgentHost } from "@posthog/core/sessions/commentToAgent";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { persistImageFile } from "@posthog/ui/features/message-editor/utils/persistFile";
import { track } from "@posthog/ui/shell/analytics";
import { showTaskChat } from "./showTaskChat";

export const commentToAgentHost: CommentToAgentHost = {
  persistScreenshot: async (dataUrl) => {
    const blob = await (await fetch(dataUrl)).blob();
    const file = new File([blob], "comment-screenshot.png", {
      type: blob.type || "image/png",
    });
    return (await persistImageFile(file)).path;
  },
  getDraft: (taskId) => useDraftStore.getState().actions.getDraft(taskId),
  hasPendingInsert: (taskId) =>
    !!useDraftStore.getState().pendingInsert[taskId],
  insertIntoDraft: (taskId, content) =>
    useDraftStore.getState().actions.insertPendingContent(taskId, content),
  showTaskChat,
  trackCommentSent: (properties) =>
    track(ANALYTICS_EVENTS.COMMENT_SENT_TO_AGENT, properties),
};
