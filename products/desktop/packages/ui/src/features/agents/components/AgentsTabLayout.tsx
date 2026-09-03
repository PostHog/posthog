import { GearSixIcon, RobotIcon } from "@phosphor-icons/react";
import { Tabs, TabsList, TabsTrigger } from "@posthog/quill";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderDescription,
  PageHeaderFilters,
  PageHeaderHeading,
  PageHeaderNav,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import { Link, useNavigate } from "@tanstack/react-router";
import { type ReactNode, useMemo } from "react";

export type AgentsTab = "agents" | "signals" | "memory";

const TABS: { key: AgentsTab; label: string }[] = [
  { key: "agents", label: "Agents" },
  { key: "signals", label: "Signals" },
  { key: "memory", label: "Memory" },
];

const TAB_ROUTE = {
  agents: "/agents/scouts",
  signals: "/agents/scouts/findings",
  memory: "/agents/scouts/scratchpad",
} as const;

const TAB_DESCRIPTION: Record<AgentsTab, string> = {
  agents:
    "Scheduled agents that watch this project and send what they find to Self-driving.",
  signals:
    "Everything your agents surfaced recently, newest first, with the Self-driving report each one fed into.",
  memory:
    "Notes your agents keep about this project as they scan it: what they classified, ruled out, or named.",
};

/** Page chrome shared by the three fleet-level tabs. */
export function AgentsTabLayout({
  tab,
  counts,
  actions,
  children,
}: {
  tab: AgentsTab;
  counts?: Partial<Record<AgentsTab, number>>;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const navigate = useNavigate();
  const headerContent = useMemo(
    () => (
      <div className="flex w-full min-w-0 items-center gap-2">
        <RobotIcon size={12} className="shrink-0 text-gray-10" />
        <span className="truncate whitespace-nowrap font-medium text-[13px]">
          Agents
        </span>
      </div>
    ),
    [],
  );
  useSetHeaderContent(headerContent);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader>
        <PageHeaderHeading>
          <PageHeaderTitleRow>
            <PageHeaderTitle>Agents</PageHeaderTitle>
            {actions ? <PageHeaderActions>{actions}</PageHeaderActions> : null}
          </PageHeaderTitleRow>
          <PageHeaderDescription>{TAB_DESCRIPTION[tab]}</PageHeaderDescription>
        </PageHeaderHeading>
        <PageHeaderNav>
          <Tabs
            value={tab}
            className="min-w-0 overflow-x-auto"
            onValueChange={(value: string) => {
              navigate({ to: TAB_ROUTE[value as AgentsTab] });
            }}
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
          <PageHeaderFilters className="pb-2">
            <Link
              to="/settings/$category"
              params={{ category: "agents" }}
              className="flex items-center gap-1.5 text-[12px] text-gray-10 no-underline hover:text-gray-12"
              data-attr="agents-open-sources"
            >
              <GearSixIcon size={13} />
              Connections and sources
            </Link>
          </PageHeaderFilters>
        </PageHeaderNav>
      </PageHeader>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto max-w-[90rem] px-6 py-6">{children}</div>
      </div>
    </div>
  );
}
