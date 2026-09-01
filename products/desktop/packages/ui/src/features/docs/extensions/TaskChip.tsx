import {
  Badge,
  cn,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { useTaskSummaries } from "@posthog/ui/features/tasks/useTasks";
import { useNavigate } from "@tanstack/react-router";
import { mergeAttributes, Node } from "@tiptap/core";
import {
  NodeViewWrapper,
  type ReactNodeViewProps,
  ReactNodeViewRenderer,
} from "@tiptap/react";

/**
 * A task, inline in a doc.
 *
 * The node stores the task id and the title it had when it was inserted. Status,
 * owner, and the pull request are read live, so the doc never has to be rewritten
 * when the work moves on.
 */

export interface TaskChipAttrs {
  taskId: string;
  label: string;
}

const RUNNING_STATUSES = new Set(["queued", "in_progress", "not_started"]);
const DONE_STATUSES = new Set(["completed"]);
const FAILED_STATUSES = new Set(["failed", "cancelled"]);

function statusTone(status: string | null | undefined): {
  dot: string;
  label: string;
} {
  if (!status) return { dot: "bg-(--gray-8)", label: "Not started" };
  if (RUNNING_STATUSES.has(status))
    return { dot: "bg-(--amber-9)", label: "Running" };
  if (DONE_STATUSES.has(status))
    return { dot: "bg-(--grass-9)", label: "Done" };
  if (FAILED_STATUSES.has(status))
    return { dot: "bg-(--tomato-9)", label: "Stopped" };
  return { dot: "bg-(--gray-8)", label: status };
}

export function TaskChipView({ node, extension }: ReactNodeViewProps) {
  const { taskId, label } = node.attrs as TaskChipAttrs;
  const { channelId, onOpenThread } = extension.options as TaskChipOptions;
  const navigate = useNavigate();
  const { data: summaries } = useTaskSummaries(taskId ? [taskId] : []);
  const summary = summaries?.[0];
  const tone = statusTone(summary?.latest_run?.status);

  return (
    <NodeViewWrapper as="span" className="inline-block align-baseline">
      <Tooltip>
        <TooltipTrigger
          render={
            <Badge
              variant="default"
              className="cursor-pointer gap-1.5"
              onClick={() => {
                if (onOpenThread) {
                  onOpenThread(taskId);
                  return;
                }
                navigate({
                  to: "/spaces/$channelId/tasks/$taskId",
                  params: { channelId, taskId },
                });
              }}
            />
          }
        >
          <span className={cn("size-1.5 rounded-full", tone.dot)} />
          {summary?.title ?? label ?? "Task"}
        </TooltipTrigger>
        <TooltipContent>
          {tone.label}
          {summary?.repository ? ` · ${summary.repository}` : ""}
        </TooltipContent>
      </Tooltip>
    </NodeViewWrapper>
  );
}

export interface TaskChipOptions {
  /** The space the doc lives in, so a click can open the task in place. */
  channelId: string;
  /** Set for a thread that belongs to this doc: a click opens it beside the page. */
  onOpenThread?: (taskId: string) => void;
}

export const TaskChip = Node.create<TaskChipOptions>({
  name: "taskChip",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,

  addOptions() {
    return { channelId: "", onOpenThread: undefined };
  },

  addAttributes() {
    return {
      taskId: { default: "" },
      label: { default: "" },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-task-chip]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes(HTMLAttributes, { "data-task-chip": "" }),
      HTMLAttributes.label ?? "Task",
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(TaskChipView);
  },
});
