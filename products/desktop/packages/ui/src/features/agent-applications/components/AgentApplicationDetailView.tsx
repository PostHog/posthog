import { Flex, Text } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
import { useAgentAnalytics } from "../hooks/useAgentAnalytics";
import { useAgentApplication } from "../hooks/useAgentApplication";
import { useAgentApplicationSessions } from "../hooks/useAgentApplicationSessions";
import { AgentAnalyticsKpiStrip } from "./AgentAnalyticsView";
import { AgentDetailEmptyState, AgentDetailLayout } from "./AgentDetailLayout";
import { AgentSessionRow } from "./AgentSessionRow";

/**
 * Per-agent Overview pane: the top-level observability KPIs (spend / sessions /
 * failure rate / p95 over the last 7 days, with trends + WoW deltas — the same
 * metrics as the Observability tab) plus recent sessions. Rendered inside the
 * shared {@link AgentDetailLayout} tab shell.
 */
export function AgentApplicationDetailView({ idOrSlug }: { idOrSlug: string }) {
  const { data: application } = useAgentApplication(idOrSlug);
  const { data: analytics, isLoading: analyticsLoading } = useAgentAnalytics(
    application?.id,
    "agent",
  );
  const {
    data: sessions,
    isLoading: sessionsLoading,
    isError: sessionsError,
  } = useAgentApplicationSessions(idOrSlug, { limit: 25 });

  return (
    <AgentDetailLayout idOrSlug={idOrSlug} activeTab="overview">
      <Flex direction="column" gap="6">
        <section>
          <Flex align="center" justify="between" className="mb-3">
            <Text className="font-semibold text-[13px] text-gray-12">
              Activity · last 7 days
            </Text>
            <Link
              to="/code/agents/applications/$idOrSlug/observability"
              params={{ idOrSlug }}
              className="text-[12px] text-gray-11 no-underline hover:text-gray-12"
            >
              View observability →
            </Link>
          </Flex>
          <AgentAnalyticsKpiStrip
            data={analytics}
            isLoading={analyticsLoading || !application}
          />
        </section>

        <section>
          <Text className="mb-3 block font-semibold text-[13px] text-gray-12">
            Recent sessions
          </Text>
          {sessionsLoading ? (
            <Flex direction="column" gap="2">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-[52px] animate-pulse rounded-(--radius-2) border border-border bg-(--gray-2)"
                />
              ))}
            </Flex>
          ) : sessionsError ? (
            <AgentDetailEmptyState
              title="Couldn't load recent sessions"
              description="The agent platform API returned an error."
            />
          ) : !sessions || sessions.results.length === 0 ? (
            <AgentDetailEmptyState
              title="No sessions yet"
              description="Sessions this agent runs will appear here."
            />
          ) : (
            <Flex direction="column" gap="2">
              {sessions.results.map((session) => (
                <AgentSessionRow
                  key={session.id}
                  session={session}
                  idOrSlug={idOrSlug}
                />
              ))}
            </Flex>
          )}
        </section>
      </Flex>
    </AgentDetailLayout>
  );
}
