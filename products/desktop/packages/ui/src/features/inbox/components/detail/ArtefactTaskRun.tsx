import { CaretDownIcon, CaretRightIcon } from "@phosphor-icons/react";
import type { Task, TaskRunArtefactContent } from "@posthog/shared/types";
import { TaskLogsPanel } from "@posthog/ui/features/task-detail/components/TaskLogsPanel";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { Badge, Box, Text } from "@radix-ui/themes";
import { useState } from "react";

const SIGNALS_PRODUCT = "signals";

// Friendlier labels for the built-in signals-pipeline task types; custom-agent types fall back
// to a humanized form of their identifier.
const SIGNALS_TYPE_LABELS: Record<string, string> = {
  research: "Research",
  implementation: "Implementation",
  repo_selection: "Repo selection",
};

function humanizeIdentifier(value: string): string {
  const spaced = value.replace(/[_-]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * Renders a `task_run` artefact: loads the referenced task and lets the user
 * expand it to read the full conversation log (read-only) via `TaskLogsPanel`.
 */
export function ArtefactTaskRun({
  content,
}: {
  content: TaskRunArtefactContent;
}) {
  const [expanded, setExpanded] = useState(false);

  const taskQuery = useAuthenticatedQuery<Task>(
    taskKeys.detail(content.task_id),
    (client) => client.getTask(content.task_id),
    { enabled: !!content.task_id, staleTime: 10_000 },
  );

  const task = taskQuery.data;
  const isSignals = content.product === SIGNALS_PRODUCT;
  const label = isSignals
    ? (SIGNALS_TYPE_LABELS[content.type] ?? humanizeIdentifier(content.type))
    : humanizeIdentifier(content.type);
  const status = task?.latest_run?.status;

  return (
    <Box>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        disabled={!task}
        className="-mx-1 flex w-full items-center gap-2 rounded-md px-1 py-1 text-left transition-colors hover:bg-(--gray-3) disabled:cursor-default disabled:hover:bg-transparent"
      >
        {expanded ? (
          <CaretDownIcon size={12} className="shrink-0 text-(--gray-10)" />
        ) : (
          <CaretRightIcon size={12} className="shrink-0 text-(--gray-10)" />
        )}
        <Badge color="gray" variant="soft" className="shrink-0">
          {label}
        </Badge>
        {!isSignals ? (
          <Badge color="iris" variant="soft" className="shrink-0">
            {humanizeIdentifier(content.product)}
          </Badge>
        ) : null}
        <Text className="min-w-0 flex-1 truncate text-(--gray-12) text-[12px]">
          {taskQuery.isLoading
            ? "Loading task…"
            : (task?.title ?? content.task_id)}
        </Text>
        {status ? (
          <Badge color="gray" variant="soft" className="shrink-0">
            {status}
          </Badge>
        ) : null}
      </button>

      {taskQuery.isError ? (
        <Text className="block text-(--red-11) text-[11px]">
          Couldn’t load this task.
        </Text>
      ) : null}

      {expanded && task ? (
        <Box className="mt-2 h-[420px] overflow-hidden rounded-md border border-(--gray-6)">
          <TaskLogsPanel taskId={content.task_id} task={task} hideInput />
        </Box>
      ) : null}
    </Box>
  );
}
