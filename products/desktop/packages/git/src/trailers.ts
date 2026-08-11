// Standalone (no git-saga / simple-git imports) so signed-commit.ts can append
// PostHog trailers without dragging the heavy git machinery into bundles that
// reach it (e.g. the renderer's browser build).
export function buildPostHogTrailers(taskId?: string): string[] {
  const trailers = ["Generated-By: PostHog Code"];
  if (taskId) trailers.push(`Task-Id: ${taskId}`);
  return trailers;
}
