import { z } from "zod";

export interface GoalMeasureTask {
  taskId: string;
  state: "running" | "ended";
}

const taskIdsByGoal = z.record(z.string(), z.string());

const storageKey = (channelId: string) =>
  `context-goal-measure-tasks:${channelId}`;

export function readGoalMeasureTaskIds(
  channelId: string,
): Record<string, string> {
  try {
    const raw = window.localStorage.getItem(storageKey(channelId));
    const parsed = taskIdsByGoal.safeParse(raw ? JSON.parse(raw) : null);
    return parsed.success ? parsed.data : {};
  } catch {
    return {};
  }
}

export function writeGoalMeasureTaskIds(
  channelId: string,
  ids: Record<string, string>,
): void {
  try {
    window.localStorage.setItem(storageKey(channelId), JSON.stringify(ids));
  } catch {}
}
