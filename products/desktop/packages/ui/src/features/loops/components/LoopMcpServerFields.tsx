import type { McpServerInstallation } from "@posthog/api-client/posthog-client";
import {
  resolveServerName,
  sortInstallationsByName,
} from "@posthog/core/mcp-servers/resolveServerName";
import { getInstallationStatus } from "@posthog/core/mcp-servers/status";
import { Switch } from "@posthog/quill";
import { mcpKeys } from "@posthog/ui/features/mcp-server-manager/useMcpConnect";
import { STATUS_LABELS } from "@posthog/ui/features/mcp-servers/components/parts/statusBadge";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { Button } from "@posthog/ui/primitives/Button";
import { navigateToMcpServers } from "@posthog/ui/router/navigationBridge";
import {
  isLoopMcpServerReady,
  selectableLoopMcpServers,
  unavailableLoopMcpServerIds,
} from "../loopMcpServers";

interface LoopMcpServerFieldsProps {
  selectedIds: string[];
  onChange: (selectedIds: string[]) => void;
  disabled?: boolean;
}

/** Why a not-ready connection can't be picked: the loops backend rejects ids
 * that are disabled or not OAuth-ready, so the row says what to fix in MCP
 * servers first. */
function serverHint(server: McpServerInstallation): string | null {
  if (isLoopMcpServerReady(server)) return null;
  if (server.is_enabled === false) return "Disabled";
  return STATUS_LABELS[getInstallationStatus(server)];
}

export function LoopMcpServerFields({
  selectedIds,
  onChange,
  disabled,
}: LoopMcpServerFieldsProps) {
  const { data: installations, isLoading } = useAuthenticatedQuery(
    mcpKeys.installations,
    (client) => client.getMcpServerInstallations(),
  );

  const servers = sortInstallationsByName(
    selectableLoopMcpServers(installations ?? []),
    new Map(),
  );
  const unavailableIds = unavailableLoopMcpServerIds(selectedIds, servers);
  const selected = new Set(selectedIds);

  const toggle = (id: string, checked: boolean) => {
    onChange(
      checked
        ? [...selectedIds, id]
        : selectedIds.filter((selected) => selected !== id),
    );
  };

  if (isLoading) {
    return (
      <span className="text-[12.5px] text-gray-10">Loading MCP servers…</span>
    );
  }

  if (servers.length === 0 && unavailableIds.length === 0) {
    return (
      <div className="flex flex-col items-start gap-2">
        <span className="text-[12.5px] text-gray-10">
          No MCP servers connected yet.
        </span>
        <Button
          variant="outline"
          size="1"
          disabled={disabled}
          onClick={() => navigateToMcpServers()}
        >
          Connect MCP servers
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {servers.map((server) => {
        const name = resolveServerName(server, null);
        const hint = serverHint(server);
        const ready = isLoopMcpServerReady(server);
        const checked = selected.has(server.id);
        return (
          <div
            key={server.id}
            className="flex items-center justify-between gap-2 rounded-(--radius-2) border border-border bg-(--gray-1) px-3 py-2.5"
          >
            <div className="flex min-w-0 items-baseline gap-2">
              <span className="truncate font-medium text-[13px] text-gray-12">
                {name}
              </span>
              {hint ? (
                <span className="shrink-0 text-(--amber-11) text-[12px]">
                  {hint}
                </span>
              ) : null}
            </div>
            <Switch
              checked={checked}
              // Saving a not-ready connection would fail backend validation,
              // so it can only be turned off, never newly on.
              disabled={disabled || (!checked && !ready)}
              aria-label={name}
              onCheckedChange={(next) => toggle(server.id, next)}
            />
          </div>
        );
      })}
      {unavailableIds.map((id) => (
        <div
          key={id}
          className="flex items-center justify-between gap-2 rounded-(--radius-2) border border-(--amber-6) bg-(--amber-2) px-3 py-2.5"
        >
          <span className="min-w-0 truncate text-(--amber-11) text-[12.5px]">
            This connection is no longer available.
          </span>
          <Button
            variant="outline"
            color="gray"
            size="1"
            disabled={disabled}
            onClick={() => toggle(id, false)}
          >
            Remove
          </Button>
        </div>
      ))}
    </div>
  );
}
