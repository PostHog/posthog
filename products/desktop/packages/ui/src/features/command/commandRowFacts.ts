import { channelDisplayLabel } from "@posthog/core/canvas/channelName";
import type { Task, TaskSearchResult } from "@posthog/shared/domain-types";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import type { CommandRowMetaPart } from "@posthog/ui/features/command/commandRowMeta";
import { getOriginProductMeta } from "@posthog/ui/features/sidebar/components/items/TaskIcon";
import { activityValue } from "@posthog/ui/features/sidebar/listItemAppearance";

function textPart(
  text: string | null | undefined,
): CommandRowMetaPart | undefined {
  return text?.trim() ? { text } : undefined;
}

function sourcePart(
  originProduct: string | null | undefined,
): CommandRowMetaPart | undefined {
  const meta = getOriginProductMeta(originProduct ?? undefined);
  return meta ? { text: meta.label } : undefined;
}

function activityPart(
  timestamp: number | undefined,
): CommandRowMetaPart | undefined {
  const value = activityValue(timestamp);
  return value ? { text: value.text, title: value.title } : undefined;
}

export function taskRowRecency(task: Task): number {
  return Date.parse(task.last_activity_at ?? task.updated_at);
}

export function taskRowParts(task: Task): (CommandRowMetaPart | undefined)[] {
  return [
    sourcePart(task.origin_product),
    textPart(task.repository),
    textPart(task.created_by ? userDisplayName(task.created_by) : undefined),
    activityPart(taskRowRecency(task)),
  ];
}

export function channelRowParts(channel: {
  repositories: string[];
  createdBy: { first_name?: string; last_name?: string; email?: string } | null;
}): (CommandRowMetaPart | undefined)[] {
  return [
    textPart(channel.repositories[0]),
    textPart(
      channel.createdBy ? userDisplayName(channel.createdBy) : undefined,
    ),
  ];
}

function metadataString(
  result: TaskSearchResult,
  key: string,
): string | undefined {
  const value = result.metadata[key];
  return typeof value === "string" && value ? value : undefined;
}

function searchResultLocation(
  result: TaskSearchResult,
  task: Task | undefined,
): string | undefined {
  if (result.kind === "pull_request") {
    return metadataString(result, "repository") ?? result.subtitle;
  }
  if (result.kind === "artifact") return result.subtitle;
  if (result.kind !== "task") return undefined;
  return task?.repository ?? result.subtitle;
}

export function searchResultRecency(
  result: TaskSearchResult,
  task: Task | undefined,
): number | undefined {
  const changed = task ? taskRowRecency(task) : Date.parse(result.updated_at);
  return Number.isNaN(changed) ? undefined : changed;
}

export function searchResultParts(
  result: TaskSearchResult,
  task: Task | undefined,
): (CommandRowMetaPart | undefined)[] {
  const author = task?.created_by ?? result.created_by;
  const source =
    result.kind === "task"
      ? sourcePart(task?.origin_product ?? result.origin_product)
      : undefined;
  return [
    source,
    textPart(searchResultLocation(result, task)),
    textPart(author ? userDisplayName(author) : undefined),
    activityPart(searchResultRecency(result, task)),
  ];
}

export function searchResultDetail(
  result: TaskSearchResult,
  channelName: string | undefined,
): string | undefined {
  if (result.kind === "channel") return undefined;
  return channelName ? channelDisplayLabel(channelName) : undefined;
}
