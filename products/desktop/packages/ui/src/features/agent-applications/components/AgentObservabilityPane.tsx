import { useAuthStateValue } from "../../auth/store";
import { useAgentAnalytics } from "../hooks/useAgentAnalytics";
import { useAgentApplication } from "../hooks/useAgentApplication";
import { aiObservabilityTracesUrl } from "../utils/observabilityLinks";
import { AgentAnalyticsView } from "./AgentAnalyticsView";
import { AgentDetailLayout } from "./AgentDetailLayout";

/**
 * Per-agent Observability tab: the same rollups as the fleet analytics board,
 * scoped to this one agent's `$ai_*` events (by `$agent_application_id`), plus
 * a kick-out to the full AI observability product for trace-level depth.
 *
 * The analytics query keys on the application's UUID, so it waits for the
 * agent to resolve from `idOrSlug` before firing.
 */
export function AgentObservabilityPane({ idOrSlug }: { idOrSlug: string }) {
  const region = useAuthStateValue((s) => s.cloudRegion);
  const projectId = useAuthStateValue((s) => s.currentProjectId);

  const { data: application } = useAgentApplication(idOrSlug);
  const { data, isLoading, isError, error } = useAgentAnalytics(
    application?.id,
    "agent",
  );

  return (
    <AgentDetailLayout idOrSlug={idOrSlug} activeTab="observability">
      <AgentAnalyticsView
        data={data}
        title="Observability"
        subtitle={`${application?.name ?? "This agent"} · last 7 days (14-day trend)`}
        aiObservabilityUrl={aiObservabilityTracesUrl(region, projectId)}
        isLoading={isLoading || !application}
        isError={isError}
        errorMessage={error instanceof Error ? error.message : null}
      />
    </AgentDetailLayout>
  );
}
