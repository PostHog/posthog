import { PlanApprovalSelector } from "./PlanApprovalSelector";
import type { BasePermissionProps } from "./types";

export function SwitchModePermission(props: BasePermissionProps) {
  return <PlanApprovalSelector {...props} />;
}
