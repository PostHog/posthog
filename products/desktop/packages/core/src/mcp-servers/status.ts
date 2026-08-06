import type { McpServerInstallation } from "@posthog/api-client/types";

export type InstallationStatus = "connected" | "pending_oauth" | "needs_reauth";

export function getInstallationStatus(
  installation: McpServerInstallation,
): InstallationStatus {
  if (installation.pending_oauth) return "pending_oauth";
  if (installation.needs_reauth) return "needs_reauth";
  return "connected";
}
