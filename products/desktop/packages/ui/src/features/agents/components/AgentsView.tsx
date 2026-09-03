import { PlusIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { FleetOverviewButton } from "@posthog/ui/features/scouts/components/FleetOverviewButton";
import { NewAgentDialog } from "@posthog/ui/features/scouts/components/NewAgentDialog";
import { ScoutsFleetView } from "@posthog/ui/features/scouts/components/ScoutsFleetView";
import { useScoutConfigs } from "@posthog/ui/features/scouts/hooks/useScoutConfigs";
import { track } from "@posthog/ui/shell/analytics";
import { useState } from "react";
import { AgentsTabLayout } from "./AgentsTabLayout";

export function AgentsView() {
  const [newAgentOpen, setNewAgentOpen] = useState(false);
  const { data: configs } = useScoutConfigs();

  const openNewAgent = () => {
    track(ANALYTICS_EVENTS.SCOUT_ACTION, {
      action_type: "open_new_agent",
      surface: "fleet_list",
    });
    setNewAgentOpen(true);
  };

  return (
    <AgentsTabLayout
      tab="agents"
      counts={{ agents: configs?.length }}
      actions={
        <>
          <FleetOverviewButton />
          <Button
            type="button"
            variant="primary"
            size="sm"
            onClick={openNewAgent}
            data-attr="agents-new-agent"
          >
            <PlusIcon size={13} weight="bold" />
            New agent
          </Button>
        </>
      }
    >
      <ScoutsFleetView onNewAgent={openNewAgent} />
      <NewAgentDialog open={newAgentOpen} onOpenChange={setNewAgentOpen} />
    </AgentsTabLayout>
  );
}
