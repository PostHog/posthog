import { buildChannelItems } from "@posthog/core/canvas/channelItems";
import { Button, ItemGroup, ItemSeparator } from "@posthog/quill";
import { ChannelItemSummary } from "@posthog/ui/features/canvas/components/ChannelItemPreview";
import type { DotTone } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useTaskSummaries } from "@posthog/ui/features/tasks/useTasks";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "@tanstack/react-router";
import { useMemo } from "react";
import { DocRefDot } from "../DocRefDot";
import type { InlineRefKind, InlineRefState } from "../types";

export interface TaskRefAttrs {
  taskId: string;
  label: string;
}

const RUNNING_STATUSES = new Set(["queued", "in_progress", "not_started"]);
const DONE_STATUSES = new Set(["completed"]);
const FAILED_STATUSES = new Set(["failed", "cancelled"]);

interface TaskTone {
  tone: DotTone;
  style: "solid" | "hollow";
  pulse: boolean;
  label: string;
}

function taskTone(status: string | null | undefined): TaskTone {
  if (!status)
    return {
      tone: "gray",
      style: "hollow",
      pulse: false,
      label: "Not started",
    };
  if (RUNNING_STATUSES.has(status))
    return { tone: "yellow", style: "solid", pulse: true, label: "Running" };
  if (DONE_STATUSES.has(status))
    return { tone: "green", style: "solid", pulse: false, label: "Done" };
  if (FAILED_STATUSES.has(status))
    return { tone: "red", style: "solid", pulse: false, label: "Stopped" };
  return { tone: "gray", style: "hollow", pulse: false, label: status };
}

/**
 * The card a task opens on hover: the same summary the sessions list shows,
 * without its menu. The task is read only while the card is open.
 */
function TaskHoverCard({
  taskId,
  onOpen,
}: {
  taskId: string;
  onOpen?: () => void;
}) {
  const { data: task } = useQuery(taskDetailQuery(taskId));
  const item = useMemo(
    () =>
      task
        ? buildChannelItems({
            dashboards: [],
            feedTasks: [task],
            archivedTaskIds: new Set(),
            pinnedTaskIds: new Set(),
            ownedBy: null,
          })[0]
        : null,
    [task],
  );
  return (
    <ItemGroup className="w-80 gap-0!">
      {item ? (
        <ChannelItemSummary item={item} />
      ) : (
        <div className="space-y-2 p-3">
          <div className="h-4 w-3/5 animate-pulse rounded bg-(--gray-a4)" />
          <div className="h-9 w-full animate-pulse rounded bg-(--gray-a3)" />
        </div>
      )}
      {onOpen ? (
        <>
          <ItemSeparator className="my-0" />
          <div className="flex justify-end p-1.5">
            <Button variant="link-muted" size="xs" onClick={onOpen}>
              Open task ↗
            </Button>
          </div>
        </>
      ) : null}
    </ItemGroup>
  );
}

function useTaskRef({ taskId, label }: TaskRefAttrs): InlineRefState {
  const { data: summaries } = useTaskSummaries(taskId ? [taskId] : []);
  const summary = summaries?.[0];
  const tone = taskTone(summary?.latest_run?.status);
  const navigate = useNavigate();
  const channelId = useParams({
    strict: false,
    select: (params) => params.channelId,
  });
  const title = label || summary?.title || "Task";
  const onOpen = channelId
    ? () =>
        void navigate({
          to: "/spaces/$channelId/tasks/$taskId",
          params: { channelId, taskId },
        })
    : undefined;

  return {
    label: title,
    mark: <DocRefDot tone={tone.tone} style={tone.style} pulse={tone.pulse} />,
    card: {
      title,
      render: () => <TaskHoverCard taskId={taskId} onOpen={onOpen} />,
    },
    onOpen,
  };
}

/**
 * A task, inline in a doc.
 *
 * The node stores the task id and the title it had when it was inserted.
 * Status, owner, and the repository are read live, so the doc never has to be
 * rewritten when the work moves on. A click opens the task in this space.
 */
export const taskRef: InlineRefKind<TaskRefAttrs> = {
  name: "taskChip",
  attributes: { taskId: { default: "" }, label: { default: "" } },
  parseTag: "span[data-task-chip]",
  domAttributes: ({ taskId }) => ({ "data-task-chip": taskId }),
  fallbackLabel: ({ label }) => label || "Task",
  useRef: useTaskRef,
};
