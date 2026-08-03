import { BroadcastIcon, CaretRightIcon } from "@phosphor-icons/react";
import { formatRelativeTimeShort } from "@posthog/shared";
import type {
  AgentApplication,
  AgentFleetLiveSessionSummary,
  AgentSessionTriggerMetadata,
} from "@posthog/shared/agent-platform-types";
import { Badge } from "@posthog/ui/primitives/Badge";
import { Flex, Text } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
import { useMemo } from "react";
import { useAgentApplications } from "../hooks/useAgentApplications";
import { useAgentFleetLiveSessions } from "../hooks/useAgentFleetLiveSessions";
import { sessionStateColor } from "../utils/format";
import { RefreshIndicator } from "./RefreshIndicator";

/**
 * Cross-agent in-flight sessions, surfaced on the Fleet landing. Lists
 * non-terminal sessions across the fleet with state, agent, trigger, turn count
 * and started-ago; clicking a row navigates to the per-agent session detail.
 * Polls aggressively (see {@link useAgentFleetLiveSessions}) so the panel feels
 * live without an SSE channel.
 */
export function AgentFleetLiveSessionsPanel() {
  const { data, isLoading, isError, isFetching, dataUpdatedAt, refetch } =
    useAgentFleetLiveSessions();
  const { data: applications } = useAgentApplications();

  const appsById = useMemo(() => {
    const map = new Map<string, AgentApplication>();
    for (const app of applications ?? []) {
      map.set(app.id, app);
    }
    return map;
  }, [applications]);

  const sessions = data?.results ?? [];

  return (
    <section>
      <Flex align="center" justify="between" className="mb-3">
        <Flex align="center" gap="2">
          <BroadcastIcon size={13} className="text-gray-11" />
          <Text className="font-semibold text-[13px] text-gray-12">
            Live now
          </Text>
          {sessions.length > 0 ? (
            <Badge color="blue">{sessions.length}</Badge>
          ) : null}
        </Flex>
        <RefreshIndicator
          updatedAt={dataUpdatedAt}
          isFetching={isFetching}
          onRefresh={() => void refetch()}
        />
      </Flex>

      {isLoading ? (
        <Flex direction="column" gap="2">
          {[0, 1].map((i) => (
            <div
              key={i}
              className="h-[52px] animate-pulse rounded-(--radius-2) border border-border bg-(--gray-2)"
            />
          ))}
        </Flex>
      ) : isError ? (
        <EmptyTile
          title="Couldn't load live sessions"
          description="The agent platform API returned an error."
        />
      ) : sessions.length === 0 ? (
        <EmptyTile
          title="Nothing running"
          description="In-flight agent sessions across the fleet will show up here."
        />
      ) : (
        <Flex direction="column" gap="2">
          {sessions.map((session) => (
            <LiveSessionRow
              key={session.id}
              session={session}
              application={appsById.get(session.application_id)}
            />
          ))}
        </Flex>
      )}
    </section>
  );
}

function LiveSessionRow({
  session,
  application,
}: {
  session: AgentFleetLiveSessionSummary;
  application: AgentApplication | undefined;
}) {
  const agentLabel =
    application?.name ?? application?.slug ?? session.application_id;
  const idOrSlug =
    application?.slug ?? application?.id ?? session.application_id;
  const trigger = triggerLabel(session.trigger_metadata);
  return (
    <Link
      to="/code/agents/applications/$idOrSlug/sessions/$sessionId"
      params={{ idOrSlug, sessionId: session.id }}
      className="flex items-center justify-between gap-3 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-4 py-3 no-underline transition-colors duration-150 hover:border-(--gray-6) hover:bg-(--gray-2)"
    >
      <Flex align="center" gap="3" className="min-w-0">
        <Badge color={sessionStateColor(session.state)}>{session.state}</Badge>
        <Flex direction="column" gap="0.5" className="min-w-0">
          <Text className="truncate font-medium text-[12.5px] text-gray-12">
            {agentLabel}
          </Text>
          <Text className="truncate text-[11px] text-gray-10">
            {trigger ? `${trigger} · ` : ""}
            {session.turns} turn{session.turns === 1 ? "" : "s"}
            {session.preview ? ` · ${session.preview}` : ""}
          </Text>
        </Flex>
      </Flex>
      <Flex align="center" gap="3" className="shrink-0">
        <Text className="text-[11px] text-gray-10">
          {formatRelativeTimeShort(session.created_at)}
        </Text>
        <CaretRightIcon size={14} className="shrink-0 text-gray-10" />
      </Flex>
    </Link>
  );
}

function triggerLabel(
  meta: AgentSessionTriggerMetadata | null | undefined,
): string | null {
  if (!meta || typeof meta !== "object") return null;
  const kind = (meta as { kind?: unknown }).kind;
  return typeof kind === "string" ? kind : null;
}

function EmptyTile({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <Flex
      direction="column"
      align="center"
      gap="1"
      className="rounded-(--radius-2) border border-(--gray-5) border-dashed px-6 py-8 text-center"
    >
      <Text className="font-medium text-[12.5px] text-gray-12">{title}</Text>
      <Text className="max-w-md text-[11.5px] text-gray-11 leading-snug">
        {description}
      </Text>
    </Flex>
  );
}
