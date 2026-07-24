import type { GitFileStatus } from "@posthog/shared/domain-types";

export type StatusColor = "green" | "orange" | "red" | "blue" | "gray";
export interface StatusIndicator {
  label: string;
  fullLabel: string;
  color: StatusColor;
}
export function getStatusIndicator(status: GitFileStatus): StatusIndicator {
  switch (status) {
    case "added":
    case "untracked":
      return { label: "A", fullLabel: "Added", color: "green" };
    case "deleted":
      return { label: "D", fullLabel: "Deleted", color: "red" };
    case "modified":
      return { label: "M", fullLabel: "Modified", color: "orange" };
    case "renamed":
      return { label: "R", fullLabel: "Renamed", color: "blue" };
    default:
      return { label: "?", fullLabel: "Unknown", color: "gray" };
  }
}
