import { useSessionSelector } from "../sessions/useSession";
import { useTasks } from "../tasks/useTasks";
import {
  resolveCloudPrSummaries,
  resolveCloudPrUrl,
  resolveCloudPrUrls,
} from "./cloudPrUrl";

export { resolveCloudPrUrl };

/** Hook wrapper for components that don't already have the task/session. */
export function useCloudPrUrl(taskId: string): string | null {
  return useCloudPrUrls(taskId)[0] ?? null;
}

export function useCloudPrUrls(taskId: string): string[] {
  const { data: tasks = [] } = useTasks();
  const task = tasks.find((t) => t.id === taskId);
  const cloudOutput = useSessionSelector(
    taskId,
    (session) => session?.cloudOutput,
  );
  const session = cloudOutput ? { cloudOutput } : undefined;
  return resolveCloudPrUrls(task, session);
}

export function useCloudPrSummaries(taskId: string): Record<string, string> {
  const { data: tasks = [] } = useTasks();
  const task = tasks.find((t) => t.id === taskId);
  const cloudOutput = useSessionSelector(
    taskId,
    (session) => session?.cloudOutput,
  );
  const session = cloudOutput ? { cloudOutput } : undefined;
  return resolveCloudPrSummaries(task, session);
}
