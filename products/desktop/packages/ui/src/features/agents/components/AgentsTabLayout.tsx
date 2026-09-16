import {
  type AgentsTab,
  useAgentsPageActions,
} from "@posthog/ui/features/agents/agentsPageStore";
import { leaveSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { TabStrip } from "@posthog/ui/primitives/TabStrip";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

const TABS: readonly { key: AgentsTab; label: string }[] = [
  { key: "agents", label: "Agents" },
  { key: "memory", label: "Memory" },
  { key: "setup", label: "Setup" },
];

const TAB_DESCRIPTION: Record<AgentsTab, ReactNode> = {
  agents: (
    <>
      Scheduled agents that watch this project and write reports in{" "}
      <Link to="/inbox" onClick={leaveSettings} className="underline">
        Self-driving
      </Link>
      .
    </>
  ),
  memory:
    "Notes your agents keep about this project as they scan it: what they classified, ruled out, or named.",
  setup:
    "What your agents watch, what they can reach, and where their reports land.",
};

/** Page chrome shared by the tabs of the Agents settings page. */
export function AgentsTabLayout({
  tab,
  actions,
  fill = false,
  children,
}: {
  tab: AgentsTab;
  actions?: ReactNode;
  /** The tab owns the height and scrolls its own list, as the agent table does. */
  fill?: boolean;
  children: ReactNode;
}) {
  const { showTab } = useAgentsPageActions();

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-end gap-3 border-(--gray-5) border-b px-6">
        <TabStrip
          tabs={TABS}
          value={tab}
          onValueChange={showTab}
          dataAttrPrefix="agents-tab"
          className="min-w-0 flex-1 overflow-x-auto"
        />
        {actions ? (
          <div className="flex shrink-0 items-center gap-2 pb-1.5">
            {actions}
          </div>
        ) : null}
      </div>

      {/* A filling tab scrolls its own list, so the page itself must not scroll. */}
      <div
        className={
          fill ? "flex min-h-0 flex-1 flex-col" : "min-h-0 flex-1 overflow-auto"
        }
      >
        <div
          className={`mx-auto flex w-full max-w-[90rem] flex-col gap-3 px-6 py-5 ${fill ? "min-h-0 flex-1" : ""}`}
        >
          <p className="max-w-3xl text-[12.5px] text-gray-11 leading-snug">
            {TAB_DESCRIPTION[tab]}
          </p>
          {children}
        </div>
      </div>
    </div>
  );
}
