import { ArrowLeftIcon, RobotIcon } from "@phosphor-icons/react";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { Badge } from "@posthog/ui/primitives/Badge";
import { Flex, Text } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
import { type ReactNode, useMemo } from "react";
import { AgentBuilderHeaderControls } from "../agent-builder/AgentBuilderHeaderControls";
import type { AgentBuilderPageContext } from "../agent-builder/agentBuilderStore";
import { useSetAgentBuilderPage } from "../agent-builder/useSetAgentBuilderPage";
import { useAgentApplication } from "../hooks/useAgentApplication";

/** Map a detail sub-tab to the agent builder page context for this agent. */
function tabToAgentBuilderPage(
  tab: AgentDetailTab,
  slug: string,
  configRevision?: string,
): AgentBuilderPageContext {
  switch (tab) {
    case "chat":
      return { kind: "agent-chat", slug };
    case "sessions":
      return { kind: "agent-sessions", slug };
    case "configuration":
      return { kind: "agent-config", slug, revision: configRevision };
    case "memory":
      return { kind: "agent-memory", slug };
    case "approvals":
      return { kind: "agent-approvals", slug };
    case "observability":
      return { kind: "agent-observability", slug };
    default:
      return { kind: "agent", slug };
  }
}

export type AgentDetailTab =
  | "overview"
  | "chat"
  | "sessions"
  | "users"
  | "configuration"
  | "memory"
  | "approvals"
  | "observability";

const TABS: { id: AgentDetailTab; label: string; to: string }[] = [
  {
    id: "overview",
    label: "Overview",
    to: "/code/agents/applications/$idOrSlug",
  },
  {
    id: "configuration",
    label: "Configuration",
    to: "/code/agents/applications/$idOrSlug/configuration",
  },
  {
    id: "sessions",
    label: "Sessions",
    to: "/code/agents/applications/$idOrSlug/sessions",
  },
  {
    id: "users",
    label: "Users",
    to: "/code/agents/applications/$idOrSlug/users",
  },
  {
    id: "memory",
    label: "Memory",
    to: "/code/agents/applications/$idOrSlug/memory",
  },
  {
    id: "approvals",
    label: "Approvals",
    to: "/code/agents/applications/$idOrSlug/approvals",
  },
  {
    id: "observability",
    label: "Observability",
    to: "/code/agents/applications/$idOrSlug/observability",
  },
  {
    id: "chat",
    label: "Chat",
    to: "/code/agents/applications/$idOrSlug/chat",
  },
];

/**
 * Shared chrome for a single agent's detail panes: back link, title + state
 * badge + description, and the sub-tab bar. Each pane (Overview, Approvals, …)
 * renders its body as `children`; the layout owns the agent fetch and gates the
 * body on it so every pane shows consistent loading/error states. The session
 * transcript view deliberately does NOT use this layout — it keeps its own
 * focused full-screen chrome.
 */
export function AgentDetailLayout({
  idOrSlug,
  activeTab,
  children,
  /**
   * Fill mode: the content area becomes a full-height, full-width,
   * non-scrolling flex child and the pane manages its own layout/scroll (for
   * master-detail panes like Approvals). Default is a centered, padded,
   * scrolling document column.
   */
  fill = false,
  /**
   * Resolved revision the Configuration pane is showing. Threaded into the
   * agent-builder page context so revision-scoped punch-outs (`set_secret`,
   * `connect_mcp`) target the revision the user is looking at.
   */
  configRevision,
}: {
  idOrSlug: string;
  activeTab: AgentDetailTab;
  children: ReactNode;
  fill?: boolean;
  configRevision?: string | null;
}) {
  const {
    data: application,
    isLoading,
    isError,
  } = useAgentApplication(idOrSlug);

  const title = application?.name ?? idOrSlug;
  const headerContent = useMemo(
    () => (
      <Flex align="center" gap="2" className="w-full min-w-0">
        <RobotIcon size={12} className="shrink-0 text-gray-10" />
        <Text
          className="truncate whitespace-nowrap font-medium text-[13px]"
          title={title}
        >
          {title}
        </Text>
      </Flex>
    ),
    [title],
  );
  useSetHeaderContent(headerContent);
  const pageContext = tabToAgentBuilderPage(
    activeTab,
    idOrSlug,
    configRevision ?? undefined,
  );
  useSetAgentBuilderPage(pageContext);

  return (
    <Flex direction="column" className="h-full min-h-0">
      <Flex
        direction="column"
        gap="3"
        className="relative cursor-default select-none border-(--gray-5) border-b px-6 pt-5"
      >
        <AgentBuilderHeaderControls />
        <Link
          to="/code/agents/applications"
          className="flex w-fit items-center gap-1.5 text-[12px] text-gray-11 no-underline hover:text-gray-12"
        >
          <ArrowLeftIcon size={13} />
          Fleet
        </Link>
        <Flex align="center" gap="2" wrap="wrap" className="pr-44">
          <Text className="font-bold text-[22px] text-gray-12 leading-tight tracking-tight">
            {title}
          </Text>
          {application?.slug ? (
            <Text
              className="rounded-(--radius-1) border border-border bg-(--gray-2) px-1.5 py-0.5 text-[12px] text-gray-10 [font-family:var(--font-mono)]"
              title="Agent slug — its URL identifier"
            >
              {application.slug}
            </Text>
          ) : null}
          {application ? (
            <Badge color={application.live_revision ? "green" : "gray"}>
              {application.live_revision ? "Live" : "Draft"}
            </Badge>
          ) : null}
        </Flex>
        {application?.description?.trim() ? (
          <Text className="max-w-3xl text-[12.5px] text-gray-11 leading-snug">
            {application.description}
          </Text>
        ) : null}
        <div className="scrollbar-overlay -mb-px">
          <Flex gap="1" className="w-max">
            {TABS.map((tab) => (
              <Link
                key={tab.id}
                to={tab.to}
                params={{ idOrSlug }}
                className={`shrink-0 whitespace-nowrap border-b-2 px-3 pb-2.5 text-[12.5px] no-underline ${
                  tab.id === activeTab
                    ? "border-(--accent-9) font-medium text-gray-12"
                    : "border-transparent text-gray-11 hover:text-gray-12"
                }`}
              >
                {tab.label}
              </Link>
            ))}
          </Flex>
        </div>
      </Flex>

      {(() => {
        const gated = isLoading ? (
          <div className="h-24 animate-pulse rounded-(--radius-2) border border-border bg-(--gray-2)" />
        ) : isError || !application ? (
          <AgentDetailEmptyState
            title="Couldn't load this agent"
            description="It may have been archived, or the agent platform API returned an error."
          />
        ) : (
          children
        );
        return fill ? (
          <div className="flex min-h-0 flex-1 flex-col">{gated}</div>
        ) : (
          <div className="min-h-0 flex-1 overflow-auto">
            <div className="mx-auto max-w-4xl px-6 py-6">{gated}</div>
          </div>
        );
      })()}
    </Flex>
  );
}

export function AgentDetailEmptyState({
  title,
  description,
}: {
  title: string;
  description: ReactNode;
}) {
  return (
    <Flex
      direction="column"
      align="center"
      gap="1"
      className="rounded-(--radius-2) border border-(--gray-5) border-dashed px-6 py-10 text-center"
    >
      <Text className="font-medium text-[13px] text-gray-12">{title}</Text>
      <Text className="max-w-md text-[12px] text-gray-11 leading-snug">
        {description}
      </Text>
    </Flex>
  );
}
