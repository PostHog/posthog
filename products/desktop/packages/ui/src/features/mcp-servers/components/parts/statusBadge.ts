import type { InstallationStatus } from "@posthog/core/mcp-servers/status";

export const STATUS_LABELS: Record<InstallationStatus, string> = {
  connected: "Connected",
  pending_oauth: "Finish connecting",
  needs_reauth: "Reconnect required",
};

export const STATUS_COLORS: Record<
  InstallationStatus,
  "green" | "amber" | "red"
> = {
  connected: "green",
  pending_oauth: "amber",
  needs_reauth: "red",
};

export const PULSE_COLOR: Record<InstallationStatus, string> = {
  connected: "var(--green-9)",
  pending_oauth: "var(--amber-9)",
  needs_reauth: "var(--red-9)",
};
