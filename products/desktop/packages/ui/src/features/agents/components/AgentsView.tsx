import {
  useAgentsPageActions,
  useAgentsTab,
  useOpenAgent,
} from "@posthog/ui/features/agents/agentsPageStore";
import { ConfigureAgentsSection } from "@posthog/ui/features/inbox/components/ConfigureAgentsSection";
import { ScoutDetailView } from "@posthog/ui/features/scouts/components/ScoutDetailView";
import { ScoutFindingsView } from "@posthog/ui/features/scouts/components/ScoutFindingsView";
import { ScratchpadView } from "@posthog/ui/features/scouts/components/ScratchpadView";
import { useScoutFindings } from "@posthog/ui/features/scouts/hooks/useScoutFindings";
import { useScoutScratchpad } from "@posthog/ui/features/scouts/hooks/useScoutScratchpad";
import { useEffect } from "react";
import { AgentsFleetTab } from "./AgentsFleetTab";
import { AgentsTabLayout } from "./AgentsTabLayout";

/** The Agents settings page: the fleet, what it found, and what it connects to. */
export function AgentsView() {
  const tab = useAgentsTab();
  const agent = useOpenAgent();
  const { reset } = useAgentsPageActions();

  // Leaving settings unmounts the page. Clear it then, so opening Agents again
  // starts on the fleet rather than inside the agent someone opened last.
  useEffect(() => reset, [reset]);

  if (agent) {
    return (
      <ScoutDetailView
        skillSlug={agent.slug}
        highlightFindingId={agent.findingId}
        tab={agent.tab}
      />
    );
  }

  if (tab === "signals") return <SignalsTab />;
  if (tab === "memory") return <MemoryTab />;
  if (tab === "connections") return <ConnectionsTab />;
  return <AgentsFleetTab />;
}

function SignalsTab() {
  const { rows } = useScoutFindings();
  return (
    <AgentsTabLayout tab="signals" fill count={rows.length}>
      <ScoutFindingsView />
    </AgentsTabLayout>
  );
}

function MemoryTab() {
  const { data: entries } = useScoutScratchpad();
  return (
    <AgentsTabLayout tab="memory" fill count={entries?.length}>
      <ScratchpadView />
    </AgentsTabLayout>
  );
}

function ConnectionsTab() {
  return (
    <AgentsTabLayout tab="connections">
      <div className="max-w-[800px]">
        <ConfigureAgentsSection />
      </div>
    </AgentsTabLayout>
  );
}
