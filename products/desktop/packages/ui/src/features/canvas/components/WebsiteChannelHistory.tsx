import { CaretRightIcon } from "@phosphor-icons/react";
import type { ChannelTaskRecord } from "@posthog/core/canvas/channelTaskSchemas";
import type { DashboardSummary } from "@posthog/core/canvas/dashboardSchemas";
import { formatRelativeTimeShort } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { ChannelHeader } from "@posthog/ui/features/canvas/components/ChannelHeader";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import { useChannelTasks } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import { useDashboards } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { track } from "@posthog/ui/shell/analytics";
import { Text } from "@radix-ui/themes";
import { useNavigate } from "@tanstack/react-router";
import { type ReactNode, useEffect, useMemo } from "react";

type HistoryItem = {
  key: string;
  kind: "task" | "canvas";
  title: string;
  ts: number;
  icon: ReactNode;
  accent: string;
  onClick: () => void;
};

// A channel's history: every task and canvas created in the channel, most
// recent first. Lives behind the channel's "History" tab — the home page is now
// just the composer, with this view holding the running list of work.
export function WebsiteChannelHistory({ channelId }: { channelId: string }) {
  const navigate = useNavigate();

  useEffect(() => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "view_history",
      surface: "channel_history",
      channel_id: channelId,
    });
  }, [channelId]);

  useSetHeaderContent(
    useMemo(() => <ChannelHeader channelId={channelId} />, [channelId]),
  );

  const { dashboards } = useDashboards(channelId);
  const { tasks: filedTasks } = useChannelTasks(channelId);
  const { data: tasks } = useTasks();
  const archivedTaskIds = useArchivedTaskIds();

  const items = useMemo<HistoryItem[]>(() => {
    const canvasItems: HistoryItem[] = dashboards.map(
      (d: DashboardSummary) => ({
        key: `canvas:${d.id}`,
        kind: "canvas",
        title: d.name,
        ts: d.updatedAt,
        icon: iconForTemplate(d.templateId, {
          size: 15,
          className: "text-violet-9",
        }),
        accent: "violet",
        onClick: () =>
          navigate({
            to: "/website/$channelId/dashboards/$dashboardId",
            params: { channelId, dashboardId: d.id },
          }),
      }),
    );

    const taskById = new Map(tasks?.map((t) => [t.id, t]) ?? []);
    const taskItems: HistoryItem[] = filedTasks.flatMap(
      (f: ChannelTaskRecord) => {
        const task = taskById.get(f.taskId);
        if (archivedTaskIds.has(f.taskId) || !task) return [];
        return [
          {
            key: `task:${f.id}`,
            kind: "task" as const,
            title: task.title || "Untitled task",
            ts: Date.parse(task.updated_at) || 0,
            icon: <TaskGlyph />,
            accent: "blue",
            onClick: () =>
              navigate({
                to: "/website/$channelId/tasks/$taskId",
                params: { channelId, taskId: f.taskId },
              }),
          },
        ];
      },
    );

    // Most recent first.
    return [...canvasItems, ...taskItems].sort((a, b) => b.ts - a.ts);
  }, [dashboards, filedTasks, tasks, archivedTaskIds, channelId, navigate]);

  return (
    <div className="h-full overflow-y-auto bg-gray-1">
      <div className="mx-auto w-full max-w-[680px] px-4 py-6">
        {items.length === 0 ? (
          <div className="flex flex-col items-center gap-1 py-24 text-center">
            <Text className="font-medium text-[14px] text-gray-12">
              Nothing here yet
            </Text>
            <Text className="text-[13px] text-gray-10">
              Tasks and canvases you create in this channel show up here.
            </Text>
          </div>
        ) : (
          <div className="flex flex-col gap-0.5">
            {items.map((item) => (
              <HistoryItemRow key={item.key} item={item} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function HistoryItemRow({ item }: { item: HistoryItem }) {
  return (
    <button
      type="button"
      onClick={item.onClick}
      className="group flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-gray-3"
    >
      <span
        className="flex size-7 shrink-0 items-center justify-center rounded-md"
        style={{ backgroundColor: `var(--${item.accent}-3)` }}
      >
        {item.icon}
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate font-medium text-[13px] text-gray-12 leading-tight">
          {item.title}
        </span>
        <span className="truncate text-[11px] text-gray-10 leading-tight">
          {item.kind === "canvas" ? "Canvas" : "Task"} ·{" "}
          {formatRelativeTimeShort(item.ts)}
        </span>
      </span>
      <CaretRightIcon
        size={14}
        className="shrink-0 text-gray-8 opacity-0 transition-opacity group-hover:opacity-100"
      />
    </button>
  );
}

// A small task glyph for the history list, tinted to match the row's accent.
function TaskGlyph() {
  return (
    <span className="block size-2 rounded-full bg-blue-9" aria-hidden="true" />
  );
}
