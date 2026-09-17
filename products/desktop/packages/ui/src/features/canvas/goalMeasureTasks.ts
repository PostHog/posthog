export interface GoalMeasureTask {
  taskId: string;
  state: "running" | "ended";
}

const storageKey = (channelId: string) =>
  `context-goal-measure-tasks:${channelId}`;

export function readGoalMeasureTaskIds(
  channelId: string,
): Record<string, string> {
  try {
    const raw = window.localStorage.getItem(storageKey(channelId));
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === "object"
      ? (parsed as Record<string, string>)
      : {};
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
