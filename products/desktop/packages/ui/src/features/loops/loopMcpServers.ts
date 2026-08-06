import type { McpServerInstallation } from "@posthog/api-client/posthog-client";
import { getInstallationStatus } from "@posthog/core/mcp-servers/status";

/**
 * Connections a loop may use: only the viewer's own personal installations.
 * The installations endpoint also returns the team's shared rows, but the
 * loops backend validates connector ids against the owner's personal
 * installations, so offering anything else would fail on save. Rows without
 * a scope come from backends that predate sharing and are always the
 * caller's own, so they count as personal.
 */
export function selectableLoopMcpServers(
  installations: McpServerInstallation[],
): McpServerInstallation[] {
  return installations.filter(
    (installation) => (installation.scope ?? "personal") === "personal",
  );
}

/**
 * Whether the loops backend would accept this installation as a connector
 * right now: it must be enabled and OAuth-ready, mirroring the backend's
 * active-installation check. Not-ready rows can still be unselected, just
 * not newly selected, so a save can't fail on a known-bad id.
 */
export function isLoopMcpServerReady(
  installation: McpServerInstallation,
): boolean {
  return (
    installation.is_enabled !== false &&
    getInstallationStatus(installation) === "connected"
  );
}

/**
 * Servers the picker renders: ready (enabled and OAuth-connected)
 * connections, plus not-ready ones the user has already selected. An
 * unselected not-ready connection is hidden because it could never be
 * turned on, but a selected one must stay visible so the user can see why
 * it's flagged and unselect it, since hiding it would leave an invisible
 * selection the backend rejects on save.
 */
export function visibleLoopMcpServers(
  installations: McpServerInstallation[],
  selectedIds: string[],
): McpServerInstallation[] {
  const selected = new Set(selectedIds);
  return selectableLoopMcpServers(installations).filter(
    (installation) =>
      isLoopMcpServerReady(installation) || selected.has(installation.id),
  );
}

/**
 * Selected connector ids with no selectable connection behind them (the
 * server was uninstalled, or the id belongs to someone else). Surfaced in
 * the form so the user can unselect them instead of being blocked on save.
 */
export function unavailableLoopMcpServerIds(
  selectedIds: string[],
  selectable: McpServerInstallation[],
): string[] {
  const available = new Set(selectable.map((installation) => installation.id));
  return selectedIds.filter((id) => !available.has(id));
}
