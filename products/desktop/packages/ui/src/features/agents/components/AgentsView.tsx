import { ConfigureAgentsSection } from "@posthog/ui/features/inbox/components/ConfigureAgentsSection";
import { AgentsTabLayout } from "./AgentsTabLayout";

/**
 * The Scouts tab: the scheduled-agent / self-driving configuration that has
 * always lived under Agents. Deployed agent applications get their own tab
 * (see {@link AgentApplicationsListView}).
 */
export function AgentsView() {
  return (
    <AgentsTabLayout activeTab="scouts">
      <ConfigureAgentsSection />
    </AgentsTabLayout>
  );
}
