import { readPrUrls, type Task } from "@posthog/shared";

export type TaskStatusIconKind =
  | "pr"
  | "completed"
  | "failed"
  | "running"
  | "started"
  | "chat";

export function getTaskStatusIconKind(task: Task): TaskStatusIconKind {
  const hasPr = readPrUrls(task.latest_run?.output).length > 0;
  const status = task.latest_run?.status;
  const environment = task.latest_run?.environment;

  // Match desktop semantics, but let PR win when a cloud task also has one.
  if (hasPr) {
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

  if (status === "queued") {
    return "started";
  }

  return "chat";
}
