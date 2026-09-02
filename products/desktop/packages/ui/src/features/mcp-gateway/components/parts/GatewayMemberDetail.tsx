import { ArrowLeft, Plugs, Sliders } from "@phosphor-icons/react";
import { formatAgo } from "@posthog/core/mcp-gateway/gatewayServers";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { gatewayUserName } from "@posthog/ui/features/mcp-gateway/components/parts/avatars";
import type { GatewayRoute } from "@posthog/ui/features/mcp-gateway/gatewayRoute";
import { useGatewayMembers } from "@posthog/ui/features/mcp-gateway/hooks/useGatewayMembers";
import { useGatewayServers } from "@posthog/ui/features/mcp-gateway/hooks/useGatewayServers";
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

/** Admin view of one member: which servers they can reach, per-server revoke. */
export function GatewayMemberDetail({
  userId,
  onNavigate,
}: {
  userId: number;
  onNavigate: (route: GatewayRoute) => void;
}) {
  const { members, membersLoading, setMemberAccess } = useGatewayMembers({
    enabled: true,
  });
  const { servers, templatesById } = useGatewayServers();

  const member = members.find((entry) => entry.user.id === userId);

  if (!member) {
    return (
      <Flex direction="column" gap="4">
        <BackButton onNavigate={onNavigate} />
        <Flex align="center" justify="center" py="6">
          {membersLoading ? (
            <Spinner size="2" />
          ) : (
            <Text color="gray" className="text-sm">
              Member not found.
            </Text>
          )}
        </Flex>
      </Flex>
    );
  }

  const name = gatewayUserName(member.user);
  const firstName = name.split(" ")[0];
  const revoked = new Set(member.revoked_server_ids);
  const connected = new Set(member.connected_server_ids);
  const allowedCount = servers.length - revoked.size;

  return (
    <Flex direction="column" gap="4" className="min-w-0">
      <BackButton onNavigate={onNavigate} />

      <Flex align="start" gap="3">
        <UserAvatar user={member.user} size="lg" />
        <Flex direction="column" gap="1" className="min-w-0 flex-1">
          <Flex align="center" gap="2">
            <Text truncate className="font-bold text-xl">
              {name}
            </Text>
            <Badge
              color={member.is_org_admin ? "indigo" : "gray"}
              variant="soft"
              size="1"
            >
              {member.is_org_admin ? "admin" : "member"}
            </Badge>
          </Flex>
          <Text color="gray" className="text-sm">
            {member.user.email}
          </Text>
          <Text color="gray" className="flex items-center gap-1 text-xs">
            <Plugs size={12} /> {allowedCount} of {servers.length} servers
          </Text>
        </Flex>
      </Flex>
      <Separator size="4" />

      <Flex align="center" gap="2">
        <Text className="font-medium text-base">Server access</Text>
        <Badge color="gray" variant="soft" size="1">
          {allowedCount} of {servers.length}
        </Badge>
      </Flex>
      <div className="overflow-hidden rounded border border-gray-5">
        {servers.map((server) => {
          const on = !revoked.has(server.id);
          const template = server.template_id
            ? templatesById.get(server.template_id)
            : undefined;
          const memberConnection = server.connections.find(
            (connection) => connection.user.id === member.user.id,
          );
          const usedAgo = formatAgo(memberConnection?.last_used_at ?? null);
          const sub = !on
            ? `Access turned off for ${firstName}`
            : connected.has(server.id) || memberConnection
              ? `Connected${usedAgo ? ` · used ${usedAgo}` : ""}`
              : "Not connected yet";
          return (
            <Flex
              key={server.id}
              align="center"
              gap="3"
              className={`border-gray-5 border-b px-3 py-2 last:border-b-0 ${on ? "" : "bg-gray-2 opacity-60"}`}
            >
              <ServerIcon
                iconDomain={template?.icon_domain}
                serverUrl={server.url}
                size={26}
              />
              <Flex direction="column" className="min-w-0 flex-1">
                <Text truncate className="font-medium text-sm">
                  {server.name}
                </Text>
                <Text color="gray" truncate className="text-xs">
                  {sub}
                </Text>
              </Flex>
              {on && (
                <Button
                  variant="ghost"
                  color="gray"
                  size="1"
                  onClick={() =>
                    onNavigate({
                      view: "server",
                      serverId: server.id,
                      scope: {
                        scopeType: "member",
                        scopeUserId: member.user.id,
                        label: firstName,
                      },
                    })
                  }
                >
                  <Sliders size={11} /> Tool policies
                </Button>
              )}
              <Switch
                size="1"
                checked={on}
                onCheckedChange={(enabled) =>
                  setMemberAccess({
                    userId: member.user.id,
                    serverId: server.id,
                    enabled,
                    successMessage: enabled
                      ? `${firstName} can now use ${server.name}`
                      : `${firstName} can no longer use ${server.name}`,
                  })
                }
              />
            </Flex>
          );
        })}
        {servers.length === 0 && (
          <Text color="gray" className="block px-3 py-3 text-[13px] italic">
            No servers registered with the gateway yet.
          </Text>
        )}
      </div>
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
