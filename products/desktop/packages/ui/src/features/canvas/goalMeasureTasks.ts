import type { ContextGoal } from "@posthog/core/canvas/contextDocument";
import { isTerminalStatus, type Task } from "@posthog/shared/domain-types";
import { goalMeasureTaskTitle } from "./contextPrompt";

export interface GoalMeasureTask {
  taskId: string;
  state: "running" | "ended";
}

function newest(tasks: Task[]): Task | undefined {
  return tasks.reduce<Task | undefined>(
    (latest, task) =>
      latest && latest.created_at >= task.created_at ? latest : task,
    undefined,
  );
}

export function goalMeasureTasks(
  goals: ContextGoal[],
  channelTasks: Task[],
): Map<string, GoalMeasureTask> {
  return new Map(
    goals.flatMap((goal) => {
      if (goal.measure !== null) return [];
      const title = goalMeasureTaskTitle(goal.name);
      const task = newest(channelTasks.filter((task) => task.title === title));
      if (!task) return [];
      const state = isTerminalStatus(task.latest_run?.status)
        ? "ended"
        : "running";
      return [[goal.name, { taskId: task.id, state }] as const];
    }),
  );
}
