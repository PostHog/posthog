import {
  type AgentsTab,
  agentsPageActions,
} from "@posthog/ui/features/agents/agentsPageStore";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";

/** Open the Agents settings page on one of its tabs. */
export function openAgentsPage(tab: AgentsTab = "agents"): void {
  agentsPageActions().showTab(tab);
  openSettings("agents");
}

/** Open one agent inside the Agents settings page. */
export function openAgentPage(slug: string, findingId?: string): void {
  agentsPageActions().openAgent(slug, { findingId });
  openSettings("agents");
}
