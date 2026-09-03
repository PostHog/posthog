import { CaretRight, MagnifyingGlass, X } from "@phosphor-icons/react";
import type {
  McpGatewayMemberSummary,
  McpGatewayServer,
  McpServiceAccount,
} from "@posthog/api-client/posthog-client";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import {
  gatewayUserName,
  RobotAvatar,
} from "@posthog/ui/features/mcp-gateway/components/parts/avatars";
import type { GatewayRoute } from "@posthog/ui/features/mcp-gateway/gatewayRoute";
import { useGatewayMembers } from "@posthog/ui/features/mcp-gateway/hooks/useGatewayMembers";
import { useGatewayServers } from "@posthog/ui/features/mcp-gateway/hooks/useGatewayServers";
import { useServiceAccounts } from "@posthog/ui/features/mcp-gateway/hooks/useServiceAccounts";
import {
  Badge,
  Flex,
  Heading,
  IconButton,
  Switch,
  Text,
  TextField,
} from "@radix-ui/themes";
import { useState } from "react";

const MEMBER_PREVIEW_LIMIT = 10;

/** Admin roster: agent service accounts first, then members. */
export function GatewayTeamView({
  onNavigate,
}: {
  onNavigate: (route: GatewayRoute) => void;
}) {
  const { servers } = useGatewayServers();
  const serviceAccounts = useServiceAccounts();
  const { members } = useGatewayMembers({ enabled: true });
  const [memberSearch, setMemberSearch] = useState("");
  const [membersExpanded, setMembersExpanded] = useState(false);
  const normalizedMemberSearch = memberSearch.trim().toLowerCase();
  const filteredMembers = normalizedMemberSearch
    ? members.filter((member) => {
        const name = gatewayUserName(member.user).toLowerCase();
        const email = member.user.email?.toLowerCase() ?? "";
        return (
          name.includes(normalizedMemberSearch) ||
          email.includes(normalizedMemberSearch)
        );
      })
    : members;
  const displayedMembers = membersExpanded
    ? filteredMembers
    : filteredMembers.slice(0, MEMBER_PREVIEW_LIMIT);

  return (
    <Flex direction="column" gap="4" className="min-w-0">
      <Flex direction="column" gap="1">
        <Heading className="font-bold text-2xl">Team & agents</Heading>
        <Text color="gray" className="max-w-[560px] text-sm">
          Control access for your team members and PostHog agents.
        </Text>
      </Flex>

      <Flex align="center" gap="2">
        <Text className="font-medium text-base">Agents</Text>
        <Badge color="gray" variant="soft" size="1">
          {serviceAccounts.accounts.length}
        </Badge>
      </Flex>
      <Flex direction="column" gap="2">
        {serviceAccounts.accounts.map((account) => (
          <AgentCard
            key={account.id}
            account={account}
            servers={servers}
            onOpen={() => onNavigate({ view: "agent", accountId: account.id })}
            onToggleStatus={(paused) =>
              serviceAccounts.setStatus({
                accountId: account.id,
                name: account.name,
                status: paused ? "paused" : "active",
              })
            }
          />
        ))}
        {serviceAccounts.accounts.length === 0 && (
          <Text color="gray" className="px-1 text-[13px]">
            No agents yet.
          </Text>
        )}
      </Flex>

      <Flex align="center" gap="2" mt="2">
        <Text className="font-medium text-base">Members</Text>
        <Badge color="gray" variant="soft" size="1">
          {members.length}
        </Badge>
      </Flex>
      <TextField.Root
        value={memberSearch}
        onChange={(event) => {
          setMemberSearch(event.target.value);
          setMembersExpanded(false);
        }}
        placeholder="Search members..."
        size="2"
      >
        <TextField.Slot>
          <MagnifyingGlass size={14} />
        </TextField.Slot>
        {memberSearch && (
          <TextField.Slot>
            <IconButton
              variant="ghost"
              size="1"
              aria-label="Clear member search"
              onClick={() => {
                setMemberSearch("");
                setMembersExpanded(false);
              }}
            >
              <X size={12} />
            </IconButton>
          </TextField.Slot>
        )}
      </TextField.Root>
      <div className="overflow-hidden rounded border border-gray-5 bg-gray-2">
        {displayedMembers.map((member) => (
          <MemberRow
            key={member.user.id}
            member={member}
            serverCount={servers.length}
            onOpen={() =>
              onNavigate({ view: "member", userId: member.user.id })
            }
          />
        ))}
        {members.length === 0 && (
          <Text color="gray" className="block px-3 py-3 text-[13px] italic">
            No members found.
          </Text>
        )}
        {members.length > 0 && filteredMembers.length === 0 && (
          <Text color="gray" className="block px-3 py-3 text-[13px]">
            No members match &ldquo;{memberSearch}&rdquo;
          </Text>
        )}
        {filteredMembers.length > MEMBER_PREVIEW_LIMIT && (
          <button
            type="button"
            className="w-full px-3 py-2 text-center font-medium text-gray-11 text-xs transition-colors hover:bg-gray-3 hover:text-gray-12"
            onClick={() => setMembersExpanded((expanded) => !expanded)}
          >
            {membersExpanded ? "View less" : "View more"}
          </button>
        )}
      </div>
    </Flex>
  );
}
function AgentCard({
  account,
  servers,
  onOpen,
  onToggleStatus,
}: {
  account: McpServiceAccount;
  servers: McpGatewayServer[];
  onOpen: () => void;
  onToggleStatus: (paused: boolean) => void;
}) {
  const active = account.status === "active";
  // server_ids carries one entry per member's share, so dedupe before counting.
  const sharedServerIds = new Set(account.server_ids);
  const toolCount = servers
    .filter((server) => sharedServerIds.has(server.id))
    .reduce((total, server) => total + server.tool_count, 0);

  return (
    <div className="relative rounded-md border border-gray-5 bg-gray-2 transition-colors hover:border-gray-7 hover:bg-gray-3">
      <button
        type="button"
        onClick={onOpen}
        className="grid w-full grid-cols-[40px_1fr] items-center rounded-md p-4 pr-[180px] text-left"
      >
        <RobotAvatar size="md" />
        <Flex direction="column" className="min-w-0">
          <Text truncate className="font-medium text-sm">
            {account.name}
          </Text>
          <Text color="gray" className="text-xs">
            {sharedServerIds.size} server
            {sharedServerIds.size === 1 ? "" : "s"} · {toolCount} tools
          </Text>
        </Flex>
      </button>
      <div className="-translate-y-1/2 absolute top-1/2 right-3 flex flex-col items-end gap-1">
        <Switch
          size="1"
          checked={active}
          onCheckedChange={(checked) => onToggleStatus(!checked)}
        />
        {!active && (
          <Text color="gray" className="text-[11px]">
            Paused — all access off
          </Text>
        )}
      </div>
    </div>
  );
}

function MemberRow({
  member,
  serverCount,
  onOpen,
}: {
  member: McpGatewayMemberSummary;
  serverCount: number;
  onOpen: () => void;
}) {
  const allowed = serverCount - member.revoked_server_ids.length;
  const connected = member.connected_server_ids.length;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="grid w-full grid-cols-[24px_1fr_auto_auto_auto] items-center gap-3 border-gray-5 border-b px-3 py-2 text-left transition-colors last:border-b-0 hover:bg-gray-3"
    >
      <UserAvatar user={member.user} size="sm" />
      <Flex direction="column" className="min-w-0">
        <Text truncate className="font-medium text-sm">
          {gatewayUserName(member.user)}
        </Text>
        <Text color="gray" truncate className="text-xs">
          {member.user.email}
        </Text>
      </Flex>
      <Text color="gray" className="text-xs">
        {member.is_org_admin ? "admin" : "member"}
      </Text>
      <Text color="gray" className="text-xs">
        {allowed} of {serverCount} servers
        {connected ? ` · ${connected} connected` : ""}
      </Text>
      <CaretRight size={12} className="text-gray-10" />
    </button>
  );
}
