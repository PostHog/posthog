import type { AgentApprovalRequestState } from "@posthog/shared/agent-platform-types";

export type ApprovalFilter = AgentApprovalRequestState | "all";

export const APPROVAL_FILTERS: { id: ApprovalFilter; label: string }[] = [
  { id: "queued", label: "Queued" },
  { id: "dispatched", label: "Approved" },
  { id: "rejected", label: "Rejected" },
  { id: "expired", label: "Expired" },
  { id: "all", label: "All" },
];
