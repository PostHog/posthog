export type AutomationTaskRunStatus =
  | "not_started"
  | "queued"
  | "started"
  | "in_progress"
  | "completed"
  | "failed"
  | "cancelled";

export interface AutomationStatusInput {
  lastRunStatus: string | null;
  lastTaskRunStatus?: AutomationTaskRunStatus | null;
}

export type AutomationStatusTone = "neutral" | "warning" | "success" | "error";

export type AutomationStatusIconKind =
  | "queued"
  | "success"
  | "failed"
  | "never-run";

export interface AutomationStatusPresentation {
  label: string;
  tone: AutomationStatusTone;
  iconKind: AutomationStatusIconKind;
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
        tone: "warning",
        iconKind: "queued",
      };
    case "started":
    case "in_progress":
      return null;
    case "completed":
      return {
        label: "Success",
        tone: "success",
        iconKind: "success",
      };
    case "failed":
    case "cancelled":
      return {
        label: "Failed",
        tone: "error",
        iconKind: "failed",
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
        tone: "success",
        iconKind: "success",
      };
    case "failed":
      return {
        label: "Failed",
        tone: "error",
        iconKind: "failed",
      };
    default:
      return {
        label: "Never run",
        tone: "neutral",
        iconKind: "never-run",
      };
  }
}
