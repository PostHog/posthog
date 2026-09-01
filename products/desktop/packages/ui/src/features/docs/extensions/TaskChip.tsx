import { cn, Tooltip, TooltipContent, TooltipTrigger } from "@posthog/quill";
import { useTaskSummaries } from "@posthog/ui/features/tasks/useTasks";
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

export function TaskChipView({ node }: ReactNodeViewProps) {
  const { taskId, label } = node.attrs as TaskChipAttrs;
  const { data: summaries } = useTaskSummaries(taskId ? [taskId] : []);
  const summary = summaries?.[0];
  const tone = statusTone(summary?.latest_run?.status);

  return (
    // The click is handled by the doc, which listens for this attribute. A
    // handler inside a tooltip trigger does not survive prop merging.
    <NodeViewWrapper
      as="span"
      className="inline-block align-baseline"
      data-task-chip={taskId}
    >
      <Tooltip>
        <TooltipTrigger
          render={<button type="button" className="cursor-pointer" />}
        >
          <span className="doc-chip">
            <span
              className={cn("size-[5px] shrink-0 rounded-full", tone.dot)}
            />
            {label || summary?.title || "Task"}
          </span>
        </TooltipTrigger>
        <TooltipContent>
          {summary?.title ? `${summary.title} · ` : ""}
          {tone.label}
          {summary?.repository ? ` · ${summary.repository}` : ""}
        </TooltipContent>
      </Tooltip>
    </NodeViewWrapper>
  );
}

export interface TaskChipOptions {
  /** The space the doc lives in, used by the hover card. */
  channelId: string;
}

export const TaskChip = Node.create<TaskChipOptions>({
  name: "taskChip",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,

  addOptions() {
    return { channelId: "" };
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
