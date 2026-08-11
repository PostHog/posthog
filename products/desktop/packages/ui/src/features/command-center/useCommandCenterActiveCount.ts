import { countActiveTaskCells } from "@posthog/core/command-center/grid";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useMemo } from "react";

/**
 * How many command-center cells hold a task that still exists.
 *
 * Shared by both sidebar shells so their badges can't disagree — and so neither
 * counts a task that has since been deleted, whose id lingers in the persisted
 * cell array.
 */
export function useCommandCenterActiveCount({
  enabled = true,
}: {
  enabled?: boolean;
} = {}): number {
  const showAllUsers = useSidebarStore((s) => s.showAllUsers);
  const showInternal = useSidebarStore((s) => s.showInternal);
  const { data: allTasks = [] } = useTasks(
    { showAllUsers, showInternal },
    { enabled },
  );
  const cells = useCommandCenterStore((s) => s.cells);

  return useMemo(
    () => countActiveTaskCells(cells, new Set(allTasks.map((t) => t.id))),
    [cells, allTasks],
  );
}
