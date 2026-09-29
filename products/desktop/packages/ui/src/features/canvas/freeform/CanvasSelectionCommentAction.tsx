import type { TextCommentAnchor } from "@posthog/core/comments/anchors";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import { SelectionCommentOverlay } from "@posthog/ui/features/code-editor/components/SelectionCommentOverlay";
import {
  commentAgentContext,
  withScreenshot,
} from "@posthog/ui/features/sessions/commentAgentContext";
import {
  canvasCommentFocusKey,
  useCommentNavigationStore,
} from "@posthog/ui/features/sessions/commentNavigationStore";
import { useCreateComment } from "@posthog/ui/features/sessions/components/useComments";
import { sendCommentToAgent } from "@posthog/ui/features/sessions/sendCommentToAgent";
import type { HostCanvasTextSelection } from "./canvasSelection";

export function CanvasSelectionCommentAction({
  selection,
  taskId,
  enabled,
  dashboardId,
  canvasName,
  versionId,
  onDismiss,
}: {
  selection: HostCanvasTextSelection | null;
  taskId: string | null;
  enabled: boolean;
  dashboardId: string;
  canvasName: string;
  versionId: string | null;
  onDismiss: () => void;
}) {
  const { members } = useOrgMembers();
  const openComments = useCanvasChatPanelStore((state) => state.openComments);
  const target = { scope: "desktop_canvas" as const, itemId: dashboardId };
  const createComment = useCreateComment(target, taskId ?? undefined);

  const anchor: TextCommentAnchor | null = selection
    ? {
        kind: "text",
        quote: selection.quote,
        prefix: selection.prefix,
        suffix: selection.suffix,
        start: selection.start,
        end: selection.end,
      }
    : null;

  return (
    <SelectionCommentOverlay
      selection={
        selection
          ? {
              text: selection.quote,
              fromLine: selection.start + 1,
              toLine: selection.end + 1,
              anchor: {
                top: selection.rect.top,
                endX: selection.rect.right,
                bottom: selection.rect.bottom,
                bounds: selection.frame,
              },
            }
          : null
      }
      open={!!selection && enabled}
      filePath={canvasName}
      actionLabel="Add comment"
      placeholder="Add a comment about this selection"
      showActionText
      members={members}
      onDismiss={onDismiss}
      onSendToAgent={
        anchor && taskId
          ? (content, screenshot) =>
              sendCommentToAgent({
                taskId,
                comment: content,
                context: withScreenshot(
                  commentAgentContext(anchor, {
                    kind: "canvas",
                    name: canvasName,
                  }),
                  screenshot,
                ),
                surface: "canvas",
              })
          : undefined
      }
      onSubmit={async (_start, _end, content, mentions) => {
        if (!anchor || !enabled) return;
        openComments();
        const comment = await createComment.mutateAsync({
          content,
          context: {
            anchor,
            ...(versionId ? { canvasVersionId: versionId } : {}),
          },
          mentions,
        });
        useCommentNavigationStore
          .getState()
          .requestCommentFocus(
            canvasCommentFocusKey(dashboardId),
            target,
            comment.id,
            {
              intent: "focus-only",
            },
          );
      }}
    />
  );
}
