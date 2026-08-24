export type McpToolApprovalState = "approved" | "needs_approval" | "do_not_use";

export interface McpToolPolicy {
  serverName: string;
  toolName: string;
  installationId: string;
  approvalState: McpToolApprovalState;
  description?: string;
}

export interface McpToolPermissionRequest {
  requestId: string;
  serverName: string;
  toolName: string;
  installationId: string;
  arguments: Record<string, unknown>;
  description?: string;
}

export type McpToolPermissionDecision = "allow" | "allow_always" | "reject";

export const MCP_TOOL_PERMISSION_OPTIONS = [
  {
    kind: "allow_always",
    name: "Always allow",
    optionId: "allow_always",
  },
  { kind: "reject_once", name: "Reject", optionId: "reject" },
] as const;
