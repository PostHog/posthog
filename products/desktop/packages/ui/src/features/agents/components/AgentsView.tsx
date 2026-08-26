import { ConfigureAgentsSection } from "@posthog/ui/features/inbox/components/ConfigureAgentsSection";
import { AgentsTabLayout } from "./AgentsTabLayout";

export function AgentsView() {
  return (
    <AgentsTabLayout>
      <ConfigureAgentsSection />
    </AgentsTabLayout>
  );
}
