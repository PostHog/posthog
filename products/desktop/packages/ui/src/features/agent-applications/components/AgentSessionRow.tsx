import { formatRelativeTimeShort } from "@posthog/shared";
import type {
  AgentSessionPrincipal,
  AgentSessionSummary,
} from "@posthog/shared/agent-platform-types";
import { Badge } from "@posthog/ui/primitives/Badge";
import { Flex, Text } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
import { formatSpendUsd, sessionStateColor } from "../utils/format";

function principalLabel(principal: AgentSessionPrincipal | null): string {
  if (!principal) return "anonymous";
  return principal.kind;
}

/** A single session row linking to its transcript. Shared by Overview + Sessions. */
export function AgentSessionRow({
  session,
  idOrSlug,
}: {
  session: AgentSessionSummary;
  idOrSlug: string;
}) {
  return (
    <Link
      to="/code/agents/applications/$idOrSlug/sessions/$sessionId"
      params={{ idOrSlug, sessionId: session.id }}
      className="no-underline"
    >
      <Flex
        align="center"
        justify="between"
        gap="3"
        className="rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-4 py-3 hover:border-(--gray-7)"
      >
        <Flex direction="column" gap="1" className="min-w-0">
          <Flex align="center" gap="2" className="min-w-0">
            <Badge color={sessionStateColor(session.state)}>
              {session.state}
            </Badge>
            <Text className="truncate text-[12.5px] text-gray-12">
              {session.preview?.trim()
                ? session.preview
                : "No assistant output"}
            </Text>
          </Flex>
          <Text className="truncate text-[11px] text-gray-10">
            {principalLabel(session.principal)} · {session.turns} turns ·{" "}
            {formatSpendUsd(session.usage_total.cost_total)}
          </Text>
        </Flex>
        <Text className="shrink-0 text-[11px] text-gray-10">
          {formatRelativeTimeShort(session.updated_at)}
        </Text>
      </Flex>
    </Link>
  );
}
