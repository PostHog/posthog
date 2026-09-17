import type { Task, TaskSearchResult } from "@posthog/shared/domain-types";

export function taskHref(task: Task, channelId?: string): string {
  return channelId
    ? `/spaces/${channelId}/tasks/${task.id}`
    : `/tasks/${task.id}`;
}

export function channelHref(channelId: string): string {
  return `/spaces/${channelId}`;
}

function canvasId(result: TaskSearchResult): string | undefined {
  const value = result.metadata.canvas_id;
  return typeof value === "string" && value ? value : undefined;
}

/** Where a search match lives, or nothing when the row has no route of its own. */
export function searchResultHref(
  result: TaskSearchResult,
  { task, bluebirdEnabled }: { task?: Task; bluebirdEnabled: boolean },
): string | undefined {
  const channelId = result.channel_id ?? undefined;
  if (result.kind === "channel") {
    return channelId ? channelHref(channelId) : undefined;
  }
  if (result.kind === "canvas") {
    const canvas = canvasId(result);
    if (!canvas) return undefined;
    return channelId
      ? `/spaces/${channelId}/dashboards/${canvas}`
      : `/canvases?canvas=${canvas}`;
  }
  if (task) return taskHref(task, bluebirdEnabled ? channelId : undefined);
  if (!result.task_id) return undefined;
  return bluebirdEnabled && channelId
    ? `/spaces/${channelId}/tasks/${result.task_id}`
    : `/tasks/${result.task_id}`;
}
