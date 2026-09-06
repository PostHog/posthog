import {
  type AgentsTab,
  useAgentsPageActions,
} from "@posthog/ui/features/agents/agentsPageStore";
import { CountedTabStrip } from "@posthog/ui/primitives/CountedTabStrip";
import type { ReactNode } from "react";

const TABS: readonly { key: AgentsTab; label: string }[] = [
  { key: "agents", label: "Agents" },
  { key: "signals", label: "Signals" },
  { key: "memory", label: "Memory" },
  { key: "connections", label: "Connections" },
];

const TAB_DESCRIPTION: Record<AgentsTab, string> = {
  agents:
    "Scheduled agents that watch this project and send what they find to Self-driving.",
  signals:
    "Everything your agents surfaced recently, newest first, with the Self-driving report each one fed into.",
  memory:
    "Notes your agents keep about this project as they scan it: what they classified, ruled out, or named.",
  connections:
    "What your agents can reach, and which sources they watch for work.",
};

/** Page chrome shared by the tabs of the Agents settings page. */
export function AgentsTabLayout({
  tab,
  count,
  actions,
  fill = false,
  children,
}: {
  tab: AgentsTab;
  /** How many things this tab holds, shown beside its label. */
  count?: number;
  actions?: ReactNode;
  /** The tab owns the height and scrolls its own list, as the agent table does. */
  fill?: boolean;
  children: ReactNode;
}) {
  const { showTab } = useAgentsPageActions();

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-end gap-3 border-(--gray-5) border-b px-6">
        <CountedTabStrip
          tabs={TABS}
          value={tab}
          counts={{ [tab]: count } as Partial<Record<AgentsTab, number>>}
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

      <div
        className={
          fill ? "flex min-h-0 flex-1 flex-col" : "min-h-0 flex-1 overflow-auto"
        }
      >
        <div
          className={
            fill
              ? "mx-auto flex min-h-0 w-full max-w-[90rem] flex-1 flex-col gap-3 px-6 py-5"
              : "mx-auto flex w-full max-w-[90rem] flex-col gap-3 px-6 py-5"
          }
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
