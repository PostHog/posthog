import type { ContextGoal } from "@posthog/core/canvas/contextDocument";
import { isTerminalStatus, type Task } from "@posthog/shared/domain-types";

export interface GoalMeasureTask {
  taskId: string;
  state: "running" | "ended";
}

export function goalMeasureTasks(
  goals: ContextGoal[],
  channelTasks: Task[],
): Map<string, GoalMeasureTask> {
  const byId = new Map(channelTasks.map((task) => [task.id, task]));
  return new Map(
    goals.flatMap((goal) => {
      const task = goal.task && !goal.measure ? byId.get(goal.task) : undefined;
      if (!task) return [];
      const state = isTerminalStatus(task.latest_run?.status)
        ? "ended"
        : "running";
      return [[goal.id, { taskId: task.id, state }] as const];
    }),
  );
}
