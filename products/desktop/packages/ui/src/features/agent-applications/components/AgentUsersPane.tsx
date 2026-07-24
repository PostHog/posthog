import { FingerprintIcon, ProhibitIcon, UserIcon } from "@phosphor-icons/react";
import { formatRelativeTimeShort } from "@posthog/shared";
import type {
  AgentUserConnection,
  AgentUserWithConnections,
} from "@posthog/shared/agent-platform-types";
import { Badge } from "@posthog/ui/primitives/Badge";
import { Button } from "@posthog/ui/primitives/Button";
import { Flex, Text } from "@radix-ui/themes";
import { useState } from "react";
import {
  useAgentUsers,
  useDisconnectAgentUserConnection,
} from "../hooks/useAgentUsers";
import { userDisplayName } from "../utils/format";
import { AgentDetailEmptyState, AgentDetailLayout } from "./AgentDetailLayout";
import { RefreshIndicator } from "./RefreshIndicator";

/**
 * Per-agent Users pane: the agent's end-users (`agent_user`) and each user's
 * linked external identities (`agent_identity_credential`). Connection metadata
 * only — credentials are never sent to the client. Lightweight operational
 * tooling: revoke a connection now; banning a user is stubbed for later.
 */
export function AgentUsersPane({ idOrSlug }: { idOrSlug: string }) {
  const { data, isLoading, isError, isFetching, dataUpdatedAt, refetch } =
    useAgentUsers(idOrSlug);

  const users = data?.results ?? [];
  const total = data?.count ?? users.length;

  return (
    <AgentDetailLayout idOrSlug={idOrSlug} activeTab="users">
      <Flex direction="column" gap="4">
        <Flex align="center" justify="between" gap="3">
          <Flex align="center" gap="2">
            <Text className="font-semibold text-[13px] text-gray-12">
              Users
            </Text>
            {!isLoading && !isError ? (
              <Text className="text-[12px] text-gray-10 tabular-nums">
                {total}
              </Text>
            ) : null}
          </Flex>
          <RefreshIndicator
            updatedAt={dataUpdatedAt}
            isFetching={isFetching}
            onRefresh={() => void refetch()}
          />
        </Flex>

        <Text className="text-[12px] text-gray-10 leading-snug">
          People who have interacted with this agent and the external identities
          they've linked, so the agent can act as them. Credentials are never
          shown — only the connection.
        </Text>

        {isLoading ? (
          <UsersSkeleton />
        ) : isError ? (
          <AgentDetailEmptyState
            title="Couldn't load users"
            description="The agent platform API returned an error fetching this agent's users."
          />
        ) : users.length === 0 ? (
          <AgentDetailEmptyState
            title="No users yet"
            description="Once people interact with this agent, they'll appear here with any identities they link."
          />
        ) : (
          <Flex direction="column" gap="2">
            {users.map((user) => (
              <UserCard key={user.id} idOrSlug={idOrSlug} user={user} />
            ))}
          </Flex>
        )}
      </Flex>
    </AgentDetailLayout>
  );
}

function UserCard({
  idOrSlug,
  user,
}: {
  idOrSlug: string;
  user: AgentUserWithConnections;
}) {
  const displayName = userDisplayName(user);

  return (
    <div className="rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-4 py-3">
      <Flex align="center" justify="between" gap="3">
        <Flex align="center" gap="2.5" className="min-w-0">
          <UserIcon size={18} className="shrink-0 text-gray-11" />
          <Flex direction="column" gap="0.5" className="min-w-0">
            <Flex align="center" gap="2" className="min-w-0">
              <Badge color="gray">{user.principal_kind}</Badge>
              <Text className="truncate text-[12.5px] text-gray-12 [font-family:var(--font-mono)]">
                {displayName ?? user.principal_id}
              </Text>
            </Flex>
            <Text className="text-[11px] text-gray-10">
              {displayName ? `${user.principal_id} · ` : ""}first seen{" "}
              {formatRelativeTimeShort(user.created_at)}
            </Text>
          </Flex>
        </Flex>
        {/* Banning a user is not yet supported by the backend — stubbed so the
            placement is visible while we design the semantics. */}
        <Button
          size="1"
          variant="ghost"
          color="gray"
          disabled
          title="Banning users isn't available yet"
        >
          <ProhibitIcon size={13} />
          Ban
        </Button>
      </Flex>

      <div className="mt-2.5 border-(--gray-4) border-t pt-2.5">
        {user.connections.length === 0 ? (
          <Text className="text-[11.5px] text-gray-10">
            No linked connections.
          </Text>
        ) : (
          <Flex direction="column" gap="1.5">
            {user.connections.map((c) => (
              <ConnectionRow
                key={c.id}
                idOrSlug={idOrSlug}
                agentUserId={user.id}
                connection={c}
              />
            ))}
          </Flex>
        )}
      </div>
    </div>
  );
}

function ConnectionRow({
  idOrSlug,
  agentUserId,
  connection,
}: {
  idOrSlug: string;
  agentUserId: string;
  connection: AgentUserConnection;
}) {
  const [confirming, setConfirming] = useState(false);
  const disconnect = useDisconnectAgentUserConnection(idOrSlug);
  const active = connection.state === "active";

  return (
    <Flex
      align="center"
      gap="2"
      className="rounded-(--radius-1) bg-(--gray-2) px-2.5 py-1.5"
    >
      <FingerprintIcon size={13} className="shrink-0 text-gray-10" />
      <Text className="shrink-0 text-[12px] text-gray-12 [font-family:var(--font-mono)]">
        {connection.provider}
      </Text>
      <Badge color={active ? "green" : "gray"}>{connection.state}</Badge>
      {connection.subject ? (
        <Text
          className="min-w-0 truncate text-[11px] text-gray-10"
          title={`subject: ${connection.subject}`}
        >
          {connection.subject}
        </Text>
      ) : null}
      {connection.scopes.length > 0 ? (
        <Text
          className="shrink-0 text-[11px] text-gray-10"
          title={connection.scopes.join(", ")}
        >
          {connection.scopes.length} scope
          {connection.scopes.length === 1 ? "" : "s"}
        </Text>
      ) : null}
      <Text className="ml-auto shrink-0 text-[11px] text-gray-10">
        linked {formatRelativeTimeShort(connection.created_at)}
      </Text>
      {active ? (
        confirming ? (
          <Flex align="center" gap="1" className="shrink-0">
            <Button
              size="1"
              variant="solid"
              color="red"
              disabled={disconnect.isPending}
              onClick={() =>
                disconnect.mutate(
                  { agentUserId, provider: connection.provider },
                  { onSettled: () => setConfirming(false) },
                )
              }
            >
              {disconnect.isPending ? "Revoking…" : "Confirm"}
            </Button>
            <Button
              size="1"
              variant="soft"
              color="gray"
              onClick={() => setConfirming(false)}
            >
              Cancel
            </Button>
          </Flex>
        ) : (
          <Button
            size="1"
            variant="soft"
            color="gray"
            className="shrink-0"
            onClick={() => setConfirming(true)}
          >
            Disconnect
          </Button>
        )
      ) : null}
    </Flex>
  );
}

function UsersSkeleton() {
  return (
    <Flex direction="column" gap="2">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-[84px] animate-pulse rounded-(--radius-2) border border-border bg-(--gray-2)"
        />
      ))}
    </Flex>
  );
}
