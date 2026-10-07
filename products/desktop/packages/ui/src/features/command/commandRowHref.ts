import type { Task, TaskSearchResult } from "@posthog/shared/domain-types";

export function taskHref(task: Task, channelId?: string): string {
  return channelId
    ? `/spaces/${channelId}/tasks/${task.id}`
    : `/tasks/${task.id}`;
}

export function channelHref(channelId: string): string {
  return `/spaces/${channelId}`;
}

export function canvasHref(channelId: string, canvasId: string): string {
  return `/spaces/${channelId}/dashboards/${canvasId}`;
}

function canvasId(result: TaskSearchResult): string | undefined {
  const value = result.metadata.canvas_id;
  return typeof value === "string" && value ? value : undefined;
}

/** Where a search match lives, or nothing when the row has no route of its own. */
export function searchResultHref(
  result: TaskSearchResult,
  { task }: { task?: Task },
): string | undefined {
  const channelId = result.channel_id ?? undefined;
  if (result.kind === "channel") {
    return channelId ? channelHref(channelId) : undefined;
  }
  if (result.kind === "canvas") {
    const canvas = canvasId(result);
    if (!canvas) return undefined;
    return channelId
      ? canvasHref(channelId, canvas)
      : `/canvases?canvas=${canvas}`;
  }
  if (task) return taskHref(task, channelId);
  if (!result.task_id) return undefined;
  return channelId
    ? `/spaces/${channelId}/tasks/${result.task_id}`
    : `/tasks/${result.task_id}`;
}
