import { PlusIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import {
  useAgentsPageActions,
  useAgentsTab,
  useOpenAgent,
} from "@posthog/ui/features/agents/agentsPageStore";
import { ConfigureAgentsSection } from "@posthog/ui/features/inbox/components/ConfigureAgentsSection";
import { FleetOverviewButton } from "@posthog/ui/features/scouts/components/FleetOverviewButton";
import { NewAgentDialog } from "@posthog/ui/features/scouts/components/NewAgentDialog";
import { ScoutDetailView } from "@posthog/ui/features/scouts/components/ScoutDetailView";
import { ScoutFindingsView } from "@posthog/ui/features/scouts/components/ScoutFindingsView";
import { ScoutsFleetView } from "@posthog/ui/features/scouts/components/ScoutsFleetView";
import { ScratchpadView } from "@posthog/ui/features/scouts/components/ScratchpadView";
import { useScoutConfigs } from "@posthog/ui/features/scouts/hooks/useScoutConfigs";
import { useScoutFindings } from "@posthog/ui/features/scouts/hooks/useScoutFindings";
import { useScoutScratchpad } from "@posthog/ui/features/scouts/hooks/useScoutScratchpad";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useState } from "react";
import { AgentsTabLayout } from "./AgentsTabLayout";

/** The Agents settings page: the fleet, what it found, and what it connects to. */
export function AgentsView() {
  const tab = useAgentsTab();
  const agent = useOpenAgent();
  const { showTab } = useAgentsPageActions();

  // Leaving settings unmounts the page. Send it back to the fleet then, so
  // opening Agents again does not resume inside whatever was open last.
  useEffect(() => () => showTab("agents"), [showTab]);

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
  if (tab === "setup") return <SetupTab />;
  return <FleetTab />;
}

function FleetTab() {
  const [newAgent, setNewAgent] = useState<{ brief: string } | null>(null);
  const { data: configs } = useScoutConfigs();

  const openNewAgent = (brief = "") => {
    track(ANALYTICS_EVENTS.SCOUT_ACTION, {
      action_type: "open_new_agent",
      surface: "fleet_list",
    });
    setNewAgent({ brief });
  };

  return (
    <AgentsTabLayout
      tab="agents"
      fill
      count={configs?.length}
      actions={
        <>
          <FleetOverviewButton />
          <Button
            type="button"
            variant="primary"
            size="sm"
            onClick={() => openNewAgent()}
            data-attr="agents-new-agent"
          >
            <PlusIcon size={13} weight="bold" />
            New agent
          </Button>
        </>
      }
    >
      <ScoutsFleetView onNewAgent={openNewAgent} />
      <NewAgentDialog
        key={newAgent?.brief ?? ""}
        open={newAgent !== null}
        initialBrief={newAgent?.brief ?? ""}
        onOpenChange={(open) => {
          if (!open) setNewAgent(null);
        }}
      />
    </AgentsTabLayout>
  );
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

function SetupTab() {
  return (
    <AgentsTabLayout tab="setup">
      <div className="max-w-[800px]">
        <ConfigureAgentsSection />
      </div>
    </AgentsTabLayout>
  );
}
