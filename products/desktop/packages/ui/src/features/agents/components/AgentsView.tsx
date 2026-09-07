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
import { ScoutsFleetView } from "@posthog/ui/features/scouts/components/ScoutsFleetView";
import { ScratchpadView } from "@posthog/ui/features/scouts/components/ScratchpadView";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useRef, useState } from "react";
import { AgentsTabLayout } from "./AgentsTabLayout";

/** The Agents settings page: the fleet, what it found, and what it connects to. */
export function AgentsView() {
  const tab = useAgentsTab();
  const agent = useOpenAgent();
  const { showTab } = useAgentsPageActions();

  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      // StrictMode mounts again before this check. A real exit resets only this tab.
      queueMicrotask(() => {
        if (
          !mounted.current &&
          getRouterOrNull()?.state.location.pathname !== "/settings/agents"
        )
          showTab("agents");
      });
    };
  }, [showTab]);

  if (agent) {
    return (
      <ScoutDetailView
        skillSlug={agent.slug}
        highlightFindingId={agent.findingId}
        tab={agent.tab}
      />
    );
  }

  if (tab === "memory") return <MemoryTab />;
  if (tab === "setup") return <SetupTab />;
  return <FleetTab />;
}

function FleetTab() {
  const [newAgent, setNewAgent] = useState<{ brief: string } | null>(null);

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

function MemoryTab() {
  return (
    <AgentsTabLayout tab="memory" fill>
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
