import { ArrowLeft, Clock, Sliders } from "@phosphor-icons/react";
import type {
  McpAuditEvent,
  McpGatewayServer,
} from "@posthog/api-client/posthog-client";
import {
  AUDIT_DECISION_LABELS,
  formatAgo,
  formatAuditTime,
} from "@posthog/core/mcp-gateway/gatewayServers";
import { RobotAvatar } from "@posthog/ui/features/mcp-gateway/components/parts/avatars";
import type { GatewayRoute } from "@posthog/ui/features/mcp-gateway/gatewayRoute";
import { useAgentRecentCalls } from "@posthog/ui/features/mcp-gateway/hooks/useGatewayAudit";
import { useGatewayServers } from "@posthog/ui/features/mcp-gateway/hooks/useGatewayServers";
import { useServiceAccounts } from "@posthog/ui/features/mcp-gateway/hooks/useServiceAccounts";
import { ServerIcon } from "@posthog/ui/features/mcp-servers/components/parts/icons";
import {
  Badge,
  Button,
  Flex,
  Separator,
  Spinner,
  Switch,
  Text,
} from "@radix-ui/themes";
import { useState } from "react";

const DECISION_COLORS: Record<
  McpAuditEvent["decision"],
  "green" | "indigo" | "amber" | "red"
> = {
  auto: "green",
  approved: "indigo",
  pending: "amber",
  blocked: "red",
};

/** Admin view of one agent service account: identity, servers, call history. */
export function GatewayAgentDetail({
  accountId,
  onNavigate,
}: {
  accountId: string;
  onNavigate: (route: GatewayRoute) => void;
}) {
  const serviceAccounts = useServiceAccounts();
  const { servers, templatesById } = useGatewayServers();
  const { events, eventsLoading } = useAgentRecentCalls(accountId);
  const [shownCalls, setShownCalls] = useState(5);

  const account = serviceAccounts.accounts.find(
    (entry) => entry.id === accountId,
  );

  if (!account) {
    return (
      <Flex direction="column" gap="4">
        <BackButton onNavigate={onNavigate} />
        <Flex align="center" justify="center" py="6">
          {serviceAccounts.accountsLoading ? (
            <Spinner size="2" />
          ) : (
            <Text color="gray" className="text-sm">
              Agent not found.
            </Text>
          )}
        </Flex>
      </Flex>
    );
  }

  const active = account.status === "active";
  const lastCall = formatAgo(account.last_active_at);
  const created = new Date(account.created_at).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
  // Shared servers float to the top so the agent's actual reach reads first.
  const sharedServers = servers.filter((server) =>
    account.server_ids.includes(server.id),
  );
  const otherServers = servers.filter(
    (server) => !account.server_ids.includes(server.id),
  );

  return (
    <Flex direction="column" gap="4" className="min-w-0">
      <BackButton onNavigate={onNavigate} />

      <Flex align="start" gap="3">
        <RobotAvatar size="lg" />
        <Flex direction="column" gap="1" className="min-w-0 flex-1">
          <Flex align="center" gap="2">
            <Text truncate className="font-bold text-xl">
              {account.name}
            </Text>
            {active ? (
              <Badge color="green" variant="soft" size="1">
                Active
              </Badge>
            ) : (
              <Badge color="amber" variant="soft" size="1">
                Paused
              </Badge>
            )}
          </Flex>
          {account.description && (
            <Text color="gray" className="text-sm">
              {account.description}
            </Text>
          )}
          <Text color="gray" className="flex items-center gap-1 text-xs">
            <Clock size={12} />
            {lastCall ? `last call ${lastCall}` : "no calls yet"}
          </Text>
        </Flex>
        <Button
          variant="ghost"
          color="gray"
          size="2"
          onClick={() =>
            serviceAccounts.setStatus({
              accountId: account.id,
              name: account.name,
              status: active ? "paused" : "active",
            })
          }
        >
          {active ? "Pause agent" : "Resume agent"}
        </Button>
      </Flex>
      <Separator size="4" />

      <Text className="font-medium text-base">Identity</Text>
      <div className="overflow-hidden rounded border border-gray-5">
        <KvRow label="Authenticates as">
          <Text className="font-mono text-[13px]">{account.handle}</Text>
        </KvRow>
        <KvRow label="Created">
          <Text className="text-[13px]">{created}</Text>
        </KvRow>
      </div>

      <Flex align="center" gap="2">
        <Text className="font-medium text-base">Shared servers</Text>
        <Badge color="gray" variant="soft" size="1">
          {account.server_ids.length} of {servers.length}
        </Badge>
      </Flex>
      <div className="overflow-hidden rounded border border-gray-5">
        {sharedServers.map((server) => (
          <ServerAccessRow
            key={server.id}
            server={server}
            account={account}
            shared
            iconDomain={
              server.template_id
                ? templatesById.get(server.template_id)?.icon_domain
                : undefined
            }
            onNavigate={onNavigate}
            onSetAccess={serviceAccounts.setAccess}
          />
        ))}
        {sharedServers.length > 0 && otherServers.length > 0 && (
          <div className="border-gray-5 border-b bg-gray-3 px-3 py-1.5">
            <Text
              color="gray"
              className="font-medium text-[10px] uppercase tracking-[0.06em]"
            >
              Not shared
            </Text>
          </div>
        )}
        {otherServers.map((server) => (
          <ServerAccessRow
            key={server.id}
            server={server}
            account={account}
            shared={false}
            iconDomain={
              server.template_id
                ? templatesById.get(server.template_id)?.icon_domain
                : undefined
            }
            onNavigate={onNavigate}
            onSetAccess={serviceAccounts.setAccess}
          />
        ))}
        {servers.length === 0 && (
          <Text color="gray" className="block px-3 py-3 text-[13px] italic">
            No servers registered with the gateway yet.
          </Text>
        )}
      </div>

      <Text className="font-medium text-base">Recent tool calls</Text>
      <div className="overflow-hidden rounded border border-gray-5">
        <div className="grid grid-cols-[130px_1fr_auto] gap-3 border-gray-5 border-b bg-gray-2 px-3 py-2">
          <Text
            color="gray"
            className="font-medium text-[10px] uppercase tracking-[0.06em]"
          >
            Time
          </Text>
          <Text
            color="gray"
            className="font-medium text-[10px] uppercase tracking-[0.06em]"
          >
            MCP server · tool called
          </Text>
          <Text
            color="gray"
            className="text-right font-medium text-[10px] uppercase tracking-[0.06em]"
          >
            Decision
          </Text>
        </div>
        {eventsLoading && events.length === 0 ? (
          <Flex align="center" justify="center" py="4">
            <Spinner size="1" />
          </Flex>
        ) : events.length === 0 ? (
          <Text color="gray" className="block px-3 py-3 text-[13px] italic">
            No tool calls from this agent yet.
          </Text>
        ) : (
          events.slice(0, shownCalls).map((event) => (
            <div
              key={event.id}
              className="grid grid-cols-[130px_1fr_auto] items-center gap-3 border-gray-5 border-b px-3 py-2 last:border-b-0"
            >
              <Text color="gray" className="text-xs tabular-nums">
                {formatAuditTime(event.created_at)}
              </Text>
              <Flex align="baseline" gap="2" className="min-w-0">
                <Text truncate className="font-medium text-xs">
                  {event.server_name}
                </Text>
                <Text color="gray" truncate className="text-xs">
                  {event.tool_name}()
                </Text>
              </Flex>
              <Badge
                color={DECISION_COLORS[event.decision]}
                variant="soft"
                size="1"
              >
                {AUDIT_DECISION_LABELS[event.decision]}
              </Badge>
            </div>
          ))
        )}
        {events.length > shownCalls && (
          <Flex justify="center" py="2">
            <Button
              variant="ghost"
              color="gray"
              size="1"
              onClick={() => setShownCalls((count) => count + 10)}
            >
              Show more
            </Button>
          </Flex>
        )}
      </div>
    </Flex>
  );
}

/** One gateway server with this agent's access toggle. */
function ServerAccessRow({
  server,
  account,
  shared,
  iconDomain,
  onNavigate,
  onSetAccess,
}: {
  server: McpGatewayServer;
  account: { id: string; name: string };
  shared: boolean;
  iconDomain: string | undefined;
  onNavigate: (route: GatewayRoute) => void;
  onSetAccess: (vars: {
    accountId: string;
    serverId: string;
    enabled: boolean;
    successMessage?: string;
  }) => void;
}) {
  return (
    <Flex
      align="center"
      gap="3"
      className={`border-gray-5 border-b px-3 py-2 last:border-b-0 ${shared ? "" : "bg-gray-2 opacity-60"}`}
    >
      <ServerIcon iconDomain={iconDomain} serverUrl={server.url} size={26} />
      <Flex direction="column" className="min-w-0 flex-1">
        <Text truncate className="font-medium text-sm">
          {server.name}
        </Text>
        <Text color="gray" className="text-xs">
          {server.tool_count} tools
          {shared ? " available to this agent" : ""}
        </Text>
      </Flex>
      {shared && (
        <Button
          variant="ghost"
          color="gray"
          size="1"
          onClick={() =>
            onNavigate({
              view: "server",
              serverId: server.id,
              scope: {
                scopeType: "agent",
                scopeServiceAccountId: account.id,
                label: account.name,
              },
            })
          }
        >
          <Sliders size={11} /> Tool policies
        </Button>
      )}
      <Switch
        size="1"
        checked={shared}
        onCheckedChange={(enabled) =>
          onSetAccess({
            accountId: account.id,
            serverId: server.id,
            enabled,
            successMessage: enabled
              ? `${account.name} can now use ${server.name}`
              : `${account.name} no longer has access to ${server.name}`,
          })
        }
      />
    </Flex>
  );
}

function BackButton({
  onNavigate,
}: {
  onNavigate: (route: GatewayRoute) => void;
}) {
  return (
    <Flex align="center" gap="2">
      <Button
        variant="ghost"
        color="gray"
        size="1"
        onClick={() => onNavigate({ view: "team" })}
      >
        <ArrowLeft size={12} />
        Back to team & agents
      </Button>
    </Flex>
  );
}

function KvRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-[160px_1fr] items-center gap-3 border-gray-5 border-b px-3 py-2 last:border-b-0">
      <Text color="gray" className="text-xs">
        {label}
      </Text>
      {children}
    </div>
  );
}
