import { Tabs, TabsList, TabsTrigger } from "@posthog/quill";
import {
  type AgentsTab,
  useAgentsPageActions,
} from "@posthog/ui/features/agents/agentsPageStore";
import type { ReactNode } from "react";

const TABS: { key: AgentsTab; label: string }[] = [
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
  counts,
  actions,
  fill = false,
  children,
}: {
  tab: AgentsTab;
  counts?: Partial<Record<AgentsTab, number>>;
  actions?: ReactNode;
  /** The tab owns the height and scrolls its own list, as the agent table does. */
  fill?: boolean;
  children: ReactNode;
}) {
  const { showTab } = useAgentsPageActions();

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-end gap-3 border-(--gray-5) border-b px-6">
        <Tabs
          value={tab}
          className="min-w-0 flex-1 overflow-x-auto"
          onValueChange={(value: string) => showTab(value as AgentsTab)}
        >
          <TabsList variant="line" className="h-auto gap-0.5">
            {TABS.map(({ key, label }) => {
              const count = counts?.[key];
              return (
                <TabsTrigger
                  key={key}
                  value={key}
                  className="gap-1.5 px-2.5 py-2"
                  data-attr={`agents-tab-${key}`}
                >
                  <span className="font-medium text-[13px]">{label}</span>
                  {count !== undefined && count > 0 ? (
                    <span className="text-[12px] text-gray-10 tabular-nums">
                      {count}
                    </span>
                  ) : null}
                </TabsTrigger>
              );
            })}
          </TabsList>
        </Tabs>
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
