import { RobotIcon } from "@phosphor-icons/react";
import { AgentBuilderHeaderControls } from "@posthog/ui/features/agent-applications/agent-builder/AgentBuilderHeaderControls";
import type { AgentBuilderPageContext } from "@posthog/ui/features/agent-applications/agent-builder/agentBuilderStore";
import { useSetAgentBuilderPage } from "@posthog/ui/features/agent-applications/agent-builder/useSetAgentBuilderPage";
import { AGENT_PLATFORM_FLAG } from "@posthog/ui/features/agent-applications/featureFlag";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { Flex, Text } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
import { type ReactNode, useMemo } from "react";

export type AgentsTab = "scouts" | "applications";

/** Per-tab header copy so the chrome describes what you're actually looking at. */
const TAB_DESCRIPTION: Record<AgentsTab, string> = {
  scouts:
    "Self-driving agents that watch your project and surface work for review — enroll in the canonical fleet or author your own.",
  applications:
    "Talk it through. Ship it. Watch it work. The Agent Builder turns ideas into production agents.",
};

/**
 * Shared chrome for the two top-level Agents tabs. Each tab view renders its
 * own content inside this layout and declares which tab is active, so the
 * header + tab bar stay identical across Scouts and Fleet while detail
 * pages (a scout, an agent, a session) keep their own focused chrome.
 */
export function AgentsTabLayout({
  activeTab,
  children,
}: {
  activeTab: AgentsTab;
  children: ReactNode;
}) {
  const headerContent = useMemo(
    () => (
      <Flex align="center" gap="2" className="w-full min-w-0">
        <RobotIcon size={12} className="shrink-0 text-gray-10" />
        <Text
          className="truncate whitespace-nowrap font-medium text-[13px]"
          title="Agents"
        >
          Agents
        </Text>
      </Flex>
    ),
    [],
  );
  useSetHeaderContent(headerContent);
  const pageContext: AgentBuilderPageContext =
    activeTab === "applications" ? { kind: "agent-list" } : { kind: "scouts" };
  useSetAgentBuilderPage(pageContext);
  // The Fleet tab is gated behind the agent-platform flag.
  const applicationsEnabled = useFeatureFlag(AGENT_PLATFORM_FLAG);

  return (
    <Flex direction="column" className="h-full min-h-0">
      <div className="relative cursor-default select-none border-(--gray-5) border-b px-6 pt-5">
        <AgentBuilderHeaderControls />
        <Flex direction="column" gap="0.5" className="pr-44 pb-3.5">
          <Text className="font-bold text-[22px] text-gray-12 leading-tight tracking-tight">
            Agents
          </Text>
          <Text className="max-w-3xl text-[12.5px] text-gray-11 leading-snug">
            {applicationsEnabled
              ? TAB_DESCRIPTION[activeTab]
              : "Design, schedule, and deploy the agents that work on your product."}
          </Text>
        </Flex>
        <Flex gap="5" align="center">
          <TabLink
            to="/code/agents/scouts"
            label="Scouts"
            active={activeTab === "scouts"}
          />
          {applicationsEnabled ? (
            <TabLink
              to="/code/agents/applications"
              label="Fleet"
              active={activeTab === "applications"}
            />
          ) : null}
        </Flex>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto max-w-4xl px-6 py-6">{children}</div>
      </div>
    </Flex>
  );
}

function TabLink({
  to,
  label,
  active,
}: {
  to: string;
  label: string;
  active: boolean;
}) {
  return (
    <Link
      to={to}
      className={`-mb-px border-b-2 px-0.5 pb-2.5 text-[13px] no-underline transition-colors ${
        active
          ? "border-(--accent-9) font-medium text-gray-12"
          : "border-transparent text-gray-11 hover:text-gray-12"
      }`}
    >
      {label}
    </Link>
  );
}
