export function canvasCommentTaskId(
  generationTaskId: string | null | undefined,
  versions: { taskId?: string | null }[],
): string | null {
  return (
    generationTaskId ??
    versions.find((version) => version.taskId)?.taskId ??
    null
  );
}
