import { ArrowSquareOutIcon, TerminalIcon } from "@phosphor-icons/react";
import type { SignalReport, Task } from "@posthog/shared/types";
import { TaskRunStatusDot } from "@posthog/ui/features/inbox/components/AgentRunDetail";
import { RightColumnSection } from "@posthog/ui/features/inbox/components/RightColumnSection";
import { useReportTasks } from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { Flex, Text } from "@radix-ui/themes";
import { useNavigate } from "@tanstack/react-router";

interface ReportTasksSectionProps {
  report: SignalReport;
}

/**
 * Slim Runs caption + one row per linked task. Each row opens the run
 * detail at `/code/inbox/runs/$reportId` — the run view is where the task
 * log lives, this section is the doorway.
 */
export function ReportTasksSection({ report }: ReportTasksSectionProps) {
  const { data: reportTasks } = useReportTasks(report.id, report.status);
  const navigate = useNavigate();
  if (!reportTasks || reportTasks.length === 0) return null;

  return (
    <RightColumnSection Icon={TerminalIcon} title="Runs">
      <Flex direction="column" gap="0.5">
        {reportTasks.map(({ task, purposeLabel }) => (
          <TaskRow
            key={task.id}
            task={task}
            purposeLabel={purposeLabel}
            onOpen={() =>
              navigate({
                to: "/code/inbox/runs/$reportId",
                params: { reportId: report.id },
              })
            }
          />
        ))}
      </Flex>
    </RightColumnSection>
  );
}

function TaskRow({
  task,
  purposeLabel,
  onOpen,
}: {
  task: Task;
  purposeLabel: string;
  onOpen: () => void;
}) {
  const status = task.latest_run?.status ?? "not_started";
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group flex cursor-default select-none items-center gap-2 rounded-(--radius-1) px-1.5 py-1 text-left text-[11px] transition-colors hover:bg-(--gray-3)"
    >
      <TaskRunStatusDot status={status} />
      <Text className="shrink-0 text-gray-11">{purposeLabel}</Text>
      <Text className="ml-auto truncate text-(--gray-9)">
        {task.title || "Untitled"}
      </Text>
      <ArrowSquareOutIcon
        size={10}
        className="shrink-0 text-(--gray-9) opacity-0 transition-opacity group-hover:opacity-100"
      />
    </button>
  );
}
