import type { Task } from "../types";

export type TaskStatusIconKind =
  | "pr"
  | "completed"
  | "failed"
  | "running"
  | "started"
  | "chat";

export function getTaskStatusIconKind(task: Task): TaskStatusIconKind {
  const prUrl = task.latest_run?.output?.pr_url as string | undefined;
  const status = task.latest_run?.status;
  const environment = task.latest_run?.environment;

  // Match desktop semantics, but let PR win when a cloud task also has one.
  if (prUrl) {
    return "pr";
  }

  if (environment === "cloud") {
    return "chat";
  }

  if (status === "completed") {
    return "completed";
  }

  if (status === "failed") {
    return "failed";
  }

  if (status === "in_progress") {
    return "running";
  }

  if (status === "queued" || status === "started") {
    return "started";
  }

  return "chat";
}
