import type {
  McpAuditEvent,
  McpAuditQuickFilter,
} from "@posthog/api-client/posthog-client";
import {
  AUDIT_DECISION_LABELS,
  credentialOwnerLabel,
  formatAuditTime,
} from "@posthog/core/mcp-gateway/gatewayServers";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import {
  gatewayUserName,
  RobotAvatar,
} from "@posthog/ui/features/mcp-gateway/components/parts/avatars";
import {
  AUDIT_PAGE_SIZE,
  useGatewayAudit,
} from "@posthog/ui/features/mcp-gateway/hooks/useGatewayAudit";
import { useGatewayConfig } from "@posthog/ui/features/mcp-gateway/hooks/useGatewayConfig";
import { useServiceAccounts } from "@posthog/ui/features/mcp-gateway/hooks/useServiceAccounts";
import {
  Badge,
  Button,
  Flex,
  Heading,
  Select,
  Spinner,
  Text,
} from "@radix-ui/themes";
import { useState } from "react";

const FILTERS: { id: McpAuditQuickFilter; label: string }[] = [
  { id: "all", label: "All activity" },
  { id: "agents", label: "Agents only" },
  { id: "approvals", label: "Approvals" },
  { id: "blocked", label: "Blocked" },
];

const DECISION_COLORS: Record<
  McpAuditEvent["decision"],
  "green" | "indigo" | "amber" | "red"
> = {
  auto: "green",
  approved: "indigo",
  pending: "amber",
  blocked: "red",
};

/**
 * Tool calls routed through the gateway, with how each was decided. Admins
 * see every call in the project; members see calls made through their own
 * connections, including agent calls that used a connection they shared.
 * The backend scopes the rows, so this view renders whatever it may see.
 */
export function GatewayAuditLog() {
  const [quickFilter, setQuickFilter] = useState<McpAuditQuickFilter>("all");
  const [agentFilter, setAgentFilter] = useState<string>("all");
  const [page, setPage] = useState(0);

  const { isAdmin } = useGatewayConfig();
  const { accounts } = useServiceAccounts();
  const { events, totalCount, auditLoading, counts } = useGatewayAudit({
    quickFilter,
    actorServiceAccountId: agentFilter === "all" ? undefined : agentFilter,
    page,
  });

  const pages = Math.max(1, Math.ceil(totalCount / AUDIT_PAGE_SIZE));
  const currentPage = Math.min(page, pages - 1);
  const filtered = quickFilter !== "all" || agentFilter !== "all";

  const setFilter = (filter: McpAuditQuickFilter) => {
    setQuickFilter(filter);
    setPage(0);
  };

  return (
    <Flex direction="column" gap="4" className="min-w-0">
      <Flex direction="column" gap="1">
        <Heading className="font-bold text-2xl">Audit log</Heading>
        <Text color="gray" className="max-w-[620px] text-sm">
          {isAdmin
            ? "Every tool call routed through the gateway. Each row is one call to a tool on one of your team's MCP servers, and how the gateway decided it."
            : "Tool calls made through your MCP server connections, including calls from agents you shared them with, and how the gateway decided each one."}
        </Text>
      </Flex>

      <Flex align="center" justify="between" gap="2" wrap="wrap">
        <Flex gap="2" wrap="wrap">
          {FILTERS.map((filter) => (
            <button
              key={filter.id}
              type="button"
              aria-pressed={quickFilter === filter.id}
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                quickFilter === filter.id
                  ? "border-accent-8 bg-accent-4 text-accent-11"
                  : "border-gray-5 bg-gray-2 text-gray-11 hover:border-gray-7 hover:bg-gray-3"
              }`}
              onClick={() => setFilter(filter.id)}
            >
              {filter.label}
              {counts && (
                <span className="ml-1 text-gray-11">({counts[filter.id]})</span>
              )}
            </button>
          ))}
        </Flex>
        <Select.Root
          value={agentFilter}
          onValueChange={(value) => {
            setAgentFilter(value);
            setPage(0);
          }}
        >
          <Select.Trigger variant="surface">
            <Text color="gray" className="text-xs">
              Caller:
            </Text>{" "}
            {agentFilter === "all"
              ? "Everyone"
              : (accounts.find((account) => account.id === agentFilter)?.name ??
                "Agent")}
          </Select.Trigger>
          <Select.Content>
            <Select.Item value="all">Everyone</Select.Item>
            <Select.Group>
              <Select.Label>Agents</Select.Label>
              {accounts.map((account) => (
                <Select.Item key={account.id} value={account.id}>
                  {account.name}
                </Select.Item>
              ))}
            </Select.Group>
          </Select.Content>
        </Select.Root>
      </Flex>

      <Flex align="center" gap="2">
        <Text color="gray" className="text-[13px]">
          {totalCount} tool call{totalCount === 1 ? "" : "s"}
          {filtered ? " match your filters" : ""}
        </Text>
        {filtered && (
          <Button
            variant="ghost"
            size="1"
            onClick={() => {
              setQuickFilter("all");
              setAgentFilter("all");
              setPage(0);
            }}
          >
            Clear filters
          </Button>
        )}
      </Flex>

      <div className="overflow-hidden rounded border border-gray-5">
        <div className="grid grid-cols-[120px_180px_1fr_auto] gap-3 border-gray-5 border-b bg-gray-2 px-3 py-2">
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
            Caller
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
        {auditLoading && events.length === 0 ? (
          <Flex align="center" justify="center" py="6">
            <Spinner size="2" />
          </Flex>
        ) : events.length === 0 ? (
          <Text
            color="gray"
            className="block px-3 py-4 text-center text-[13px] italic"
          >
            No tool calls match these filters.
          </Text>
        ) : (
          events.map((event) => <AuditRow key={event.id} event={event} />)
        )}
      </div>

      <Flex align="center" justify="between" gap="2" wrap="wrap">
        <Text color="gray" className="text-xs tabular-nums">
          Showing {totalCount === 0 ? 0 : currentPage * AUDIT_PAGE_SIZE + 1}–
          {Math.min(totalCount, (currentPage + 1) * AUDIT_PAGE_SIZE)} of{" "}
          {totalCount}
        </Text>
        <Flex align="center" gap="1">
          <Button
            variant="surface"
            color="gray"
            size="1"
            disabled={currentPage === 0}
            onClick={() => setPage(currentPage - 1)}
          >
            Prev
          </Button>
          {pageWindow(currentPage, pages).map((pageNumber) => (
            <Button
              key={pageNumber}
              variant={pageNumber === currentPage ? "solid" : "surface"}
              color={pageNumber === currentPage ? undefined : "gray"}
              size="1"
              onClick={() => setPage(pageNumber)}
            >
              {pageNumber + 1}
            </Button>
          ))}
          <Button
            variant="surface"
            color="gray"
            size="1"
            disabled={currentPage >= pages - 1}
            onClick={() => setPage(currentPage + 1)}
          >
            Next
          </Button>
        </Flex>
      </Flex>
    </Flex>
  );
}

// A sliding window of page numbers so long histories don't render dozens of
// buttons; always keeps the current page centered where possible.
function pageWindow(current: number, total: number, size = 7): number[] {
  const start = Math.max(
    0,
    Math.min(current - Math.floor(size / 2), total - size),
  );
  const end = Math.min(total, start + size);
  return Array.from({ length: end - start }, (_, index) => start + index);
}

function AuditRow({ event }: { event: McpAuditEvent }) {
  const agent = event.actor_service_account;
  const user = event.actor_user;
  return (
    <div className="grid grid-cols-[120px_180px_1fr_auto] items-center gap-3 border-gray-5 border-b px-3 py-2 last:border-b-0">
      <Text color="gray" className="text-xs tabular-nums">
        {formatAuditTime(event.created_at)}
      </Text>
      <Flex direction="column" className="min-w-0">
        <Flex align="center" gap="2" className="min-w-0">
          {agent ? (
            <RobotAvatar size="sm" />
          ) : user ? (
            <UserAvatar user={user} size="xs" />
          ) : null}
          <Text truncate className="text-xs">
            {agent
              ? agent.name
              : user
                ? gatewayUserName(user)
                : event.actor_label}
          </Text>
          <Badge
            color={agent ? "indigo" : "gray"}
            variant="soft"
            size="1"
            className="uppercase"
          >
            {agent ? "agent" : user ? "human" : "deleted"}
          </Badge>
        </Flex>
        {event.credential_owner && (
          <Text color="gray" truncate className="text-[11px]">
            {credentialOwnerLabel(
              gatewayUserName(event.credential_owner),
              event.grant_scope,
            )}
          </Text>
        )}
      </Flex>
      <Flex align="baseline" gap="2" className="min-w-0">
        <Text truncate className="font-medium text-xs">
          {event.server_name}
        </Text>
        <Text color="gray" truncate className="text-xs">
          {event.tool_name}()
        </Text>
      </Flex>
      <Flex justify="end">
        <Badge color={DECISION_COLORS[event.decision]} variant="soft" size="1">
          {AUDIT_DECISION_LABELS[event.decision]}
        </Badge>
      </Flex>
    </div>
  );
}
