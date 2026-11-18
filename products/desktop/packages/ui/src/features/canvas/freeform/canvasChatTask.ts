import type { CanvasVersion } from "@posthog/core/canvas/dashboardSchemas";

// The run whose chat the canvas side panel shows: the current person's own run
// on this canvas. Another person's run never shows, even while it is in flight,
// so a shared canvas gives every editor their own conversation.
export function canvasChatTaskId(args: {
  /** The run this person just started here, before the record caught up. */
  startedTaskId: string | null;
  /** The record's generation task and its creator (undefined while loading). */
  generationTaskId: string | null;
  generationTaskCreatorUuid: string | null | undefined;
  /** Published versions, newest first. */
  versions: Pick<CanvasVersion, "taskId" | "createdByUuid">[];
  currentUserUuid: string | null | undefined;
}): string | null {
  if (args.startedTaskId) return args.startedTaskId;
  if (!args.currentUserUuid) return null;
  if (
    args.generationTaskId &&
    args.generationTaskCreatorUuid === args.currentUserUuid
  ) {
    return args.generationTaskId;
  }
  const ownVersion = args.versions.find(
    (version) =>
      !!version.taskId && version.createdByUuid === args.currentUserUuid,
  );
  return ownVersion?.taskId ?? null;
}
