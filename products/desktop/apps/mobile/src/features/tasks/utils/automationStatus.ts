import type { TaskRun } from "../types";

export interface AutomationStatusInput {
  lastRunStatus: string | null;
  lastTaskRunStatus?: TaskRun["status"] | null;
}

export interface AutomationStatusPresentation {
  label: string;
  className: string;
}

export function getAutomationStatusPresentation({
  lastRunStatus,
  lastTaskRunStatus,
}: AutomationStatusInput): AutomationStatusPresentation | null {
  switch (lastTaskRunStatus) {
    case "not_started":
    case "queued":
      return {
        label: "Queued",
        className: "bg-status-warning/20 text-status-warning",
      };
    case "started":
    case "in_progress":
      return null;
    case "completed":
      return {
        label: "Success",
        className: "bg-status-success/20 text-status-success",
      };
    case "failed":
    case "cancelled":
      return {
        label: "Failed",
        className: "bg-status-error/20 text-status-error",
      };
    default:
      break;
  }

  switch (lastRunStatus) {
    case "running":
      return null;
    case "success":
      return {
        label: "Success",
        className: "bg-status-success/20 text-status-success",
      };
    case "failed":
      return {
        label: "Failed",
        className: "bg-status-error/20 text-status-error",
      };
    default:
      return {
        label: "Never run",
        className: "bg-gray-4 text-gray-11",
      };
  }
}
