import {
  Gear,
  MagnifyingGlass,
  Plugs,
  Plus,
  Rows,
  Users,
  X,
} from "@phosphor-icons/react";
import type {
  McpGatewayServer,
  McpRecommendedServer,
} from "@posthog/api-client/posthog-client";
import {
  formatAgo,
  type GatewayRailStatus,
  getGatewayRailStatus,
  railConnectedServers,
} from "@posthog/core/mcp-gateway/gatewayServers";
import type { GatewayRoute } from "@posthog/ui/features/mcp-gateway/gatewayRoute";
import { ServerIcon } from "@posthog/ui/features/mcp-servers/components/parts/icons";
import {
  Flex,
  IconButton,
  ScrollArea,
  Text,
  TextField,
} from "@radix-ui/themes";
import type { ComponentType } from "react";
import { useMemo, useState } from "react";

interface GatewayRailProps {
  servers: McpGatewayServer[];
  templatesById: Map<string, McpRecommendedServer>;
  isAdmin: boolean;
  canAddServers: boolean;
  route: GatewayRoute;
  onNavigate: (route: GatewayRoute) => void;
}

export function GatewayRail({
  servers,
  templatesById,
  isAdmin,
  canAddServers,
  route,
  onNavigate,
}: GatewayRailProps) {
  const [search, setSearch] = useState("");

  const yourConnections = useMemo(
    () => railConnectedServers(servers, search),
    [servers, search],
  );

  const activeServerId = route.view === "server" ? route.serverId : null;

  return (
    <aside className="flex h-full min-h-0 w-[256px] shrink-0 flex-col border-gray-6 border-r bg-gray-2">
      <Flex
        align="center"
        justify="between"
        px="3"
        pt="3"
        pb="2"
        className="border-b border-b-(--gray-5)"
      >
        <Text className="font-bold text-sm">MCP servers</Text>
        {canAddServers && (
          <IconButton
            variant="ghost"
            color="gray"
            size="1"
            onClick={() => onNavigate({ view: "add" })}
            title="Add server"
          >
            <Plus size={14} />
          </IconButton>
        )}
      </Flex>

      <Flex direction="column" gap="2" px="3" pt="3">
        <TextField.Root
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search servers…"
          size="1"
        >
          <TextField.Slot>
            <MagnifyingGlass size={12} />
          </TextField.Slot>
          {search && (
            <TextField.Slot>
              <IconButton
                variant="ghost"
                size="1"
                onClick={() => setSearch("")}
              >
                <X size={10} />
              </IconButton>
            </TextField.Slot>
          )}
        </TextField.Root>
      </Flex>

      <ScrollArea className="min-h-0 flex-1">
        <Flex direction="column" gap="1" px="2" pb="3">
          <RailSectionLabel
            label="Your connections"
            count={yourConnections.length}
          />
          {yourConnections.length === 0 ? (
            <Text
              color="gray"
              className="px-[10px] py-[8px] text-[13px] italic"
            >
              No connections yet.
            </Text>
          ) : (
            yourConnections.map((server) => {
              const connection = server.your_connection;
              const status = getGatewayRailStatus(server);
              if (!connection || !status) return null;
              const usedAgo = formatAgo(connection.last_used_at);
              const sub =
                status === "connected"
                  ? usedAgo
                    ? `used ${usedAgo}`
                    : "Connected"
                  : RAIL_STATUS_SUB[status];
              return (
                <RailServerRow
                  key={server.id}
                  server={server}
                  templatesById={templatesById}
                  active={activeServerId === server.id}
                  sub={sub}
                  connectionStatus={status}
                  onClick={() =>
                    onNavigate({ view: "server", serverId: server.id })
                  }
                />
              );
            })
          )}

          <div className="mx-2 my-3 border-gray-5 border-t" />
          <RailSectionLabel label="Manage" />
          <RailLink
            icon={Plugs}
            label="All servers"
            active={route.view === "servers" || route.view === "server"}
            onClick={() => onNavigate({ view: "servers" })}
          />
          {isAdmin && (
            <RailLink
              icon={Users}
              label="Team & agents"
              active={["team", "agent", "member"].includes(route.view)}
              onClick={() => onNavigate({ view: "team" })}
            />
          )}
          {isAdmin && (
            <RailLink
              icon={Gear}
              label="Team settings"
              active={route.view === "settings"}
              onClick={() => onNavigate({ view: "settings" })}
            />
          )}
          <RailLink
            icon={Rows}
            label="Audit log"
            active={route.view === "audit"}
            onClick={() => onNavigate({ view: "audit" })}
          />
        </Flex>
      </ScrollArea>
    </aside>
  );
}

function RailSectionLabel({ label, count }: { label: string; count?: number }) {
  return (
    <Flex
      align="center"
      justify="between"
      px="2"
      pt="4"
      pb="1"
      className="tracking-[0.06em]"
    >
      <Text
        color="gray"
        className="font-medium text-[10px] uppercase leading-none"
      >
        {label}
      </Text>
      {count !== undefined && (
        <Text
          color="gray"
          className="rounded-[10px] bg-(--gray-4) px-[6px] py-[1px] text-[10px] leading-none"
        >
          {count}
        </Text>
      )}
    </Flex>
  );
}

function RailServerRow({
  server,
  templatesById,
  active,
  sub,
  connectionStatus,
  onClick,
}: {
  server: McpGatewayServer;
  templatesById: Map<string, McpRecommendedServer>;
  active: boolean;
  sub: string;
  connectionStatus?: GatewayRailStatus;
  onClick: () => void;
}) {
  const template = server.template_id
    ? templatesById.get(server.template_id)
    : undefined;
  return (
    <button
      type="button"
      onClick={onClick}
      className={`grid grid-cols-[28px_1fr_auto] items-center gap-2 rounded px-2 py-1.5 text-left transition-colors ${
        active
          ? "bg-gray-1 text-gray-12 shadow-sm"
          : "text-gray-11 hover:bg-gray-3"
      }`}
    >
      <ServerIcon
        iconDomain={template?.icon_domain}
        serverUrl={server.url}
        size={28}
      />
      <Flex direction="column" className="min-w-0 leading-[1.2]">
        <Text truncate className="font-medium text-[13px]">
          {server.name}
        </Text>
        <Text color="gray" truncate className="text-[10px] leading-none">
          {sub}
        </Text>
      </Flex>
      {connectionStatus ? (
        <span
          aria-hidden="true"
          className="h-[6px] w-[6px] rounded-full"
          style={{
            background: CONNECTION_STATUS_COLOR[connectionStatus],
            boxShadow: `0 0 0 3px color-mix(in oklch, ${CONNECTION_STATUS_COLOR[connectionStatus]} 20%, transparent)`,
          }}
        />
      ) : null}
    </button>
  );
}

const RAIL_STATUS_SUB: Record<
  Exclude<GatewayRailStatus, "connected">,
  string
> = {
  team_off: "Off for the team",
  revoked: "Access revoked",
  self_disabled: "Disabled for you",
  needs_reauth: "Reconnect required",
  pending_oauth: "Finish connecting",
};

const CONNECTION_STATUS_COLOR: Record<GatewayRailStatus, string> = {
  connected: "var(--green-9)",
  pending_oauth: "var(--amber-9)",
  needs_reauth: "var(--red-9)",
  team_off: "var(--gray-8)",
  revoked: "var(--gray-8)",
  self_disabled: "var(--gray-8)",
};

function RailLink({
  icon: Icon,
  label,
  active,
  onClick,
}: {
  icon: ComponentType<{ size?: number; className?: string }>;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-2 rounded px-2 py-1.5 text-left text-[13px] transition-colors ${
        active ? "bg-gray-1 text-gray-12" : "text-gray-11 hover:bg-gray-3"
      }`}
    >
      <Icon size={14} className={active ? "text-accent-11" : undefined} />
      <span>{label}</span>
    </button>
  );
}
