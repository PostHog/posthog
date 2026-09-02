import type { CanvasTextSelection } from "@posthog/core/canvas/freeformSchemas";
import type { TextCommentAnchor } from "@posthog/core/comments/anchors";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import { SelectionCommentOverlay } from "@posthog/ui/features/code-editor/components/SelectionCommentOverlay";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { useCreateComment } from "@posthog/ui/features/sessions/components/useComments";

export function CanvasSelectionCommentAction({
  selection,
  taskId,
  dashboardId,
  canvasName,
  versionId,
  onDismiss,
}: {
  selection: CanvasTextSelection | null;
  taskId: string | null;
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
              },
            }
          : null
      }
      open={!!selection && !!taskId}
      filePath={canvasName}
      actionLabel="Add comment"
      placeholder="Add a comment about this selection"
      showActionText
      members={members}
      onDismiss={onDismiss}
      onSubmit={async (_start, _end, content, mentions) => {
        if (!anchor || !taskId) return;
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
          .requestCommentFocus(taskId, target, comment.id, {
            intent: "focus-only",
          });
      }}
    />
  );
}
