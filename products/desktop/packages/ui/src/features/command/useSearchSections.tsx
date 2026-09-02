import { GitDiffIcon } from "@phosphor-icons/react";
import { channelDisplayName } from "@posthog/core/canvas/channelName";
import type { CommandMenuAction } from "@posthog/shared/analytics-events";
import type { Task, TaskSearchResult } from "@posthog/shared/domain-types";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { closeSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import {
  navigateToChannel,
  navigateToChannelTask,
  navigateToTaskDetail,
} from "@posthog/ui/router/navigationBridge";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { FileTextIcon } from "@radix-ui/react-icons";
import { type ReactNode, useMemo } from "react";

export type Command = {
  id: string;
  label: string;
  /** Muted trailing detail shown after a middot, e.g. a task's channel. */
  detail?: string;
  detailPrefix?: string;
  /** Muted second line under the label, where a trailing `detail` would be the
   * part a long label truncates away. */
  subtitle?: string;
  keywords?: string;
  icon: ReactNode;
  action: CommandMenuAction;
  /** Channel in scope for the bluebird open-channel / open-task actions. */
  channelId?: string;
  /** Hotkey string (e.g. "mod+b") shown right-aligned when present. */
  shortcut?: string;
  /** Running this keeps the palette open (e.g. completing a filter token). */
  keepOpen?: boolean;
  onRun: () => void;
};

export type CommandSection = { label: string; items: Command[] };

type SearchChannel = { id: string; name: string };

type UseSearchSectionsOptions = {
  remoteQuery: string;
  searchResults: TaskSearchResult[];
  tasks: Task[];
  taskSections: CommandSection[];
  channels: SearchChannel[];
  bluebirdEnabled: boolean;
  spacesLayout: boolean;
};

/** Convert remote matches into commands that open the match's owning task or space. */
export function useSearchSections({
  remoteQuery,
  searchResults,
  tasks,
  taskSections,
  channels,
  bluebirdEnabled,
  spacesLayout,
}: UseSearchSectionsOptions): CommandSection[] {
  return useMemo(() => {
    if (!remoteQuery || searchResults.length === 0) return [];

    const tasksById = new Map(tasks.map((task) => [task.id, task]));
    const visibleTaskIds = new Set(
      taskSections.flatMap((section) =>
        section.items.map((item) => item.id.replace(/^task-/, "")),
      ),
    );
    const channelIds = new Set(channels.map((channel) => channel.id));
    const items: Command[] = [];

    for (const result of searchResults) {
      if (result.kind === "channel" && !bluebirdEnabled) continue;
      if (
        (result.kind === "task" &&
          result.task_id &&
          visibleTaskIds.has(result.task_id)) ||
        (result.kind === "channel" &&
          result.channel_id &&
          channelIds.has(result.channel_id))
      ) {
        continue;
      }

      const task = result.task_id ? tasksById.get(result.task_id) : undefined;
      // Remote search answers with the backend's own name, so a channel row is
      // the one result that has not been through the channel list.
      const title =
        result.kind === "channel"
          ? channelDisplayName(result.title)
          : result.title;
      items.push({
        id: `search-${result.id}`,
        label: title,
        detail: result.subtitle || undefined,
        detailPrefix: "",
        keywords: `${remoteQuery} ${result.subtitle} ${Object.values(result.metadata).join(" ")}`,
        icon:
          result.kind === "pull_request" ? (
            <GitDiffIcon size={12} className="text-gray-11" />
          ) : result.kind === "channel" ? (
            channelGlyph(title, {
              size: 12,
              space: spacesLayout,
              className: "text-muted-foreground",
            })
          ) : (
            <FileTextIcon className="h-3 w-3 text-gray-11" />
          ),
        action: (result.kind === "channel"
          ? "open-channel"
          : result.kind === "pull_request"
            ? "open-task-from-pull-request"
            : result.kind === "artifact"
              ? "open-artifact"
              : "open-task") as CommandMenuAction,
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
          } else if (task) {
            // PR matches intentionally open their containing task. Cmd+K is a
            // navigator for Desktop context, not an external-link launcher.
            void openTask(
              task,
              result.channel_id ? { channelId: result.channel_id } : undefined,
            );
          } else if (bluebirdEnabled && result.task_id && result.channel_id) {
            navigateToChannelTask(result.channel_id, result.task_id);
          } else if (result.task_id) {
            navigateToTaskDetail(result.task_id);
          }
        },
      });
    }

    return items.length > 0 ? [{ label: "Search results", items }] : [];
  }, [
    remoteQuery,
    searchResults,
    tasks,
    taskSections,
    channels,
    bluebirdEnabled,
    spacesLayout,
  ]);
}
