import {
  useAgentsTab,
  useOpenAgent,
} from "@posthog/ui/features/agents/agentsPageStore";
import { ConfigureAgentsSection } from "@posthog/ui/features/inbox/components/ConfigureAgentsSection";
import { ScoutDetailView } from "@posthog/ui/features/scouts/components/ScoutDetailView";
import { ScoutFindingsView } from "@posthog/ui/features/scouts/components/ScoutFindingsView";
import { ScratchpadView } from "@posthog/ui/features/scouts/components/ScratchpadView";
import { AgentsFleetTab } from "./AgentsFleetTab";
import { AgentsTabLayout } from "./AgentsTabLayout";

/** The Agents settings page: the fleet, what it found, and what it connects to. */
export function AgentsView() {
  const tab = useAgentsTab();
  const agent = useOpenAgent();

  if (agent) {
    return (
      <ScoutDetailView
        skillSlug={agent.slug}
        highlightFindingId={agent.findingId}
        tab={agent.tab}
      />
    );
  }

  if (tab === "signals") return <ScoutFindingsView />;
  if (tab === "memory") return <ScratchpadView />;
  if (tab === "connections") {
    return (
      <AgentsTabLayout tab="connections">
        <div className="max-w-[800px]">
          <ConfigureAgentsSection />
        </div>
      </AgentsTabLayout>
    );
  }
  return <AgentsFleetTab />;
}
