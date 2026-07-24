import type { Task } from "@posthog/shared/domain-types";

/** Extract the PR url from a task's latest run output, if present. */
export function getTaskPrUrl(task: Task): string | null {
  const output = task.latest_run?.output;
  if (output && typeof output === "object" && !Array.isArray(output)) {
    const prUrl = (output as Record<string, unknown>).pr_url;
    if (typeof prUrl === "string" && prUrl.length > 0) {
      return prUrl;
    }
  }
  return null;
}
