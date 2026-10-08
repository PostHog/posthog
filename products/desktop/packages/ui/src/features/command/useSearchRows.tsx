import { channelDisplayName } from "@posthog/core/canvas/channelName";
import { singleLineTitle } from "@posthog/shared";
import type { CommandMenuAction } from "@posthog/shared/analytics-events";
import type { Task, TaskSearchResult } from "@posthog/shared/domain-types";
import type { CommandSection } from "@posthog/ui/features/command/commandRow";
import {
  searchResultDetail,
  searchResultParts,
  searchResultRecency,
} from "@posthog/ui/features/command/commandRowFacts";
import { searchResultHref } from "@posthog/ui/features/command/commandRowHref";
import { commandRowMeta } from "@posthog/ui/features/command/commandRowMeta";
import type { ResultRow } from "@posthog/ui/features/command/rankResultRows";
import { searchResultIcon } from "@posthog/ui/features/command/searchResultIcon";
import { closeSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import {
  navigateToCanvases,
  navigateToChannel,
  navigateToChannelDashboard,
  navigateToChannelTask,
  navigateToTaskDetail,
} from "@posthog/ui/router/navigationBridge";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { useMemo } from "react";

type SearchChannel = { id: string; name: string };

type UseSearchRowsOptions = {
  remoteQuery: string;
  searchResults: TaskSearchResult[];
  tasks: Task[];
  taskSections: CommandSection[];
  channels: SearchChannel[];
  bluebirdEnabled: boolean;
};

const SEARCH_ACTIONS: Record<TaskSearchResult["kind"], CommandMenuAction> = {
  task: "open-task",
  pull_request: "open-task-from-pull-request",
  artifact: "open-artifact",
  canvas: "open-canvas",
  channel: "open-channel",
};

function canvasIdOf(result: TaskSearchResult): string | undefined {
  const canvasId = result.metadata.canvas_id;
  return typeof canvasId === "string" && canvasId ? canvasId : undefined;
}

/** Remote matches as palette rows that open the match's owning task or space. */
export function useSearchRows({
  remoteQuery,
  searchResults,
  tasks,
  taskSections,
  channels,
  bluebirdEnabled,
}: UseSearchRowsOptions): ResultRow[] {
  return useMemo(() => {
    if (!remoteQuery || searchResults.length === 0) return [];

    const tasksById = new Map(tasks.map((task) => [task.id, task]));
    const visibleTaskIds = new Set(
      taskSections.flatMap((section) =>
        section.items.map((item) => item.id.replace(/^task-/, "")),
      ),
    );
    const channelNamesById = new Map(
      channels.map((channel) => [channel.id, channel.name] as const),
    );
    const rows: ResultRow[] = [];

    for (const result of searchResults) {
      if (result.kind === "channel" && !bluebirdEnabled) continue;
      if (
        (result.kind === "task" &&
          result.task_id &&
          visibleTaskIds.has(result.task_id)) ||
        (result.kind === "channel" &&
          result.channel_id &&
          channelNamesById.has(result.channel_id))
      ) {
        continue;
      }

      const task = result.task_id ? tasksById.get(result.task_id) : undefined;
      // Remote search answers with the backend's own name, so a channel row is
      // the one result that has not been through the channel list.
      const title =
        result.kind === "channel"
          ? channelDisplayName(result.title)
          : singleLineTitle(result.title);
      const channelName = result.channel_id
        ? channelNamesById.get(result.channel_id)
        : undefined;
      const canvasId = canvasIdOf(result);
      rows.push({
        kind: result.kind,
        recency: searchResultRecency(result, task),
        command: {
          id: `search-${result.id}`,
          label: title,
          subtitle: commandRowMeta(searchResultParts(result, task)),
          detail: searchResultDetail(result, channelName),
          detailPrefix: "",
          keywords: `${remoteQuery} ${result.subtitle} ${Object.values(result.metadata).join(" ")}`,
          icon: searchResultIcon(result, { title, task }),
          href: searchResultHref(result, { task, bluebirdEnabled }),
          action: SEARCH_ACTIONS[result.kind],
          channelId: bluebirdEnabled
            ? (result.channel_id ?? undefined)
            : undefined,
          onRun: () => {
            closeSettings();
            if (
              bluebirdEnabled &&
              result.kind === "channel" &&
              result.channel_id
            ) {
              navigateToChannel(result.channel_id);
            } else if (result.kind === "canvas" && canvasId) {
              if (result.channel_id) {
                navigateToChannelDashboard(result.channel_id, canvasId);
              } else {
                navigateToCanvases(canvasId);
              }
            } else if (task) {
              // PR matches intentionally open their containing task. Cmd+K is a
              // navigator for Desktop context, not an external-link launcher.
              void openTask(
                task,
                result.channel_id
                  ? { channelId: result.channel_id }
                  : undefined,
              );
            } else if (bluebirdEnabled && result.task_id && result.channel_id) {
              navigateToChannelTask(result.channel_id, result.task_id);
            } else if (result.task_id) {
              navigateToTaskDetail(result.task_id);
            }
          },
        },
      });
    }

    return rows;
  }, [
    remoteQuery,
    searchResults,
    tasks,
    taskSections,
    channels,
    bluebirdEnabled,
  ]);
}
