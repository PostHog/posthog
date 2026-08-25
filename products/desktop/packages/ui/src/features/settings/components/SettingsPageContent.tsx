import { CostManagementSettings } from "@posthog/ui/features/cost-management/CostManagementSettings";
import { McpServersView } from "@posthog/ui/features/mcp-servers/components/McpServersView";
import { AdvancedSettings } from "@posthog/ui/features/settings/sections/AdvancedSettings";
import { AgentsSettings } from "@posthog/ui/features/settings/sections/AgentsSettings";
import { DiscordSettings } from "@posthog/ui/features/settings/sections/DiscordSettings";
import { EnvironmentsSettings } from "@posthog/ui/features/settings/sections/environments/EnvironmentsSettings";
import { GeneralSettings } from "@posthog/ui/features/settings/sections/GeneralSettings";
import { GitHubSettings } from "@posthog/ui/features/settings/sections/GitHubSettings";
import { HarnessSettings } from "@posthog/ui/features/settings/sections/HarnessSettings";
import { NotificationsSettings } from "@posthog/ui/features/settings/sections/NotificationsSettings";
import { PersonalizationSettings } from "@posthog/ui/features/settings/sections/PersonalizationSettings";
import { PlanUsageSettings } from "@posthog/ui/features/settings/sections/PlanUsageSettings";
import { QuickAskSettings } from "@posthog/ui/features/settings/sections/QuickAskSettings";
import { ShortcutsSettings } from "@posthog/ui/features/settings/sections/ShortcutsSettings";
import { SignalSourcesSettings } from "@posthog/ui/features/settings/sections/SignalSourcesSettings";
import { SlackSettings } from "@posthog/ui/features/settings/sections/SlackSettings";
import { TerminalSettings } from "@posthog/ui/features/settings/sections/TerminalSettings";
import { WorkspacesSettings } from "@posthog/ui/features/settings/sections/WorkspacesSettings";
import { WorktreesSettings } from "@posthog/ui/features/settings/sections/worktrees/WorktreesSettings";
import type { SettingsCategory } from "@posthog/ui/features/settings/types";
import { CustomizeSidebarSettings } from "@posthog/ui/features/sidebar/components/CustomizeSidebarDialog";
import { SkillsView } from "@posthog/ui/features/skills/SkillsView";
import type { ComponentType, ReactNode } from "react";

const SETTINGS_PAGE_LAYOUT = {
  CONTAINED: "contained",
  FULL_BLEED: "full-bleed",
} as const;

type SettingsPageLayout =
  (typeof SETTINGS_PAGE_LAYOUT)[keyof typeof SETTINGS_PAGE_LAYOUT];

interface SettingsPageDefinition {
  title: string;
  component: ComponentType;
  layout: SettingsPageLayout;
}

function defineSettingsPage(
  title: string,
  component: ComponentType,
  layout: SettingsPageLayout = SETTINGS_PAGE_LAYOUT.CONTAINED,
): SettingsPageDefinition {
  return { title, component, layout };
}

const SETTINGS_PAGES: Record<SettingsCategory, SettingsPageDefinition> = {
  general: defineSettingsPage("General", GeneralSettings),
  notifications: defineSettingsPage("Notifications", NotificationsSettings),
  "plan-usage": defineSettingsPage("Plan & usage", PlanUsageSettings),
  "cost-management": defineSettingsPage(
    "Cost management",
    CostManagementSettings,
  ),
  workspaces: defineSettingsPage("Workspaces", WorkspacesSettings),
  worktrees: defineSettingsPage("Worktrees", WorktreesSettings),
  environments: defineSettingsPage("Environments", EnvironmentsSettings),
  "cloud-environments": defineSettingsPage(
    "Environments",
    EnvironmentsSettings,
  ),
  agents: defineSettingsPage("Agents", AgentsSettings),
  skills: defineSettingsPage(
    "Skills",
    SkillsView,
    SETTINGS_PAGE_LAYOUT.FULL_BLEED,
  ),
  "mcp-servers": defineSettingsPage(
    "MCP servers",
    McpServersView,
    SETTINGS_PAGE_LAYOUT.FULL_BLEED,
  ),
  personalization: defineSettingsPage(
    "Personalization",
    PersonalizationSettings,
  ),
  sidebar: defineSettingsPage("Sidebar", CustomizeSidebarSettings),
  terminal: defineSettingsPage("Terminal", TerminalSettings),
  harness: defineSettingsPage("Harness", HarnessSettings),
  shortcuts: defineSettingsPage("Shortcuts", ShortcutsSettings),
  "quick-ask": defineSettingsPage("Quick ask", QuickAskSettings),
  github: defineSettingsPage("GitHub", GitHubSettings),
  slack: defineSettingsPage("Slack", SlackSettings),
  discord: defineSettingsPage("Discord", DiscordSettings),
  // Slack notification config lives in the dedicated Slack section; the Signals
  // section links out to it rather than duplicating the controls.
  signals: defineSettingsPage("Self-driving", () => (
    <SignalSourcesSettings showSlackNotifications={false} />
  )),
  advanced: defineSettingsPage("Advanced", AdvancedSettings),
};

interface SettingsPageLayoutProps {
  children: ReactNode;
  formMode: boolean;
  icon?: ReactNode;
  title: string;
}

function SettingsPageHeader({
  formMode,
  icon,
  title,
  bordered = false,
}: Omit<SettingsPageLayoutProps, "children"> & { bordered?: boolean }) {
  if (formMode) return null;

  return (
    <div
      className={`flex items-center gap-2 ${
        bordered ? "shrink-0 border-gray-5 border-b px-6 py-4" : ""
      }`}
    >
      {icon && <span className="text-gray-10">{icon}</span>}
      <span className="font-medium text-lg leading-6.5">{title}</span>
    </div>
  );
}

function ContainedSettingsPageLayout({
  children,
  formMode,
  icon,
  title,
}: SettingsPageLayoutProps) {
  return (
    <div className="h-full w-full overflow-y-auto [scrollbar-gutter:stable_both-edges]">
      <div className="relative z-[1] mx-auto max-w-[800px] p-6">
        <div className="flex flex-col gap-5">
          <SettingsPageHeader formMode={formMode} icon={icon} title={title} />
          {children}
        </div>
      </div>
    </div>
  );
}

function FullBleedSettingsPageLayout({
  children,
  formMode,
  icon,
  title,
}: SettingsPageLayoutProps) {
  return (
    <div className="relative z-[1] flex h-full min-h-0 w-full flex-col">
      <SettingsPageHeader
        bordered
        formMode={formMode}
        icon={icon}
        title={title}
      />
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  );
}

const SETTINGS_PAGE_LAYOUT_COMPONENTS: Record<
  SettingsPageLayout,
  ComponentType<SettingsPageLayoutProps>
> = {
  [SETTINGS_PAGE_LAYOUT.CONTAINED]: ContainedSettingsPageLayout,
  [SETTINGS_PAGE_LAYOUT.FULL_BLEED]: FullBleedSettingsPageLayout,
};

interface SettingsPageContentProps {
  category: SettingsCategory;
  formMode: boolean;
  icon?: ReactNode;
}

export function SettingsPageContent({
  category,
  formMode,
  icon,
}: SettingsPageContentProps) {
  const page = SETTINGS_PAGES[category];
  const PageComponent = page.component;
  const PageLayout = SETTINGS_PAGE_LAYOUT_COMPONENTS[page.layout];

  return (
    <PageLayout formMode={formMode} icon={icon} title={page.title}>
      <PageComponent />
    </PageLayout>
  );
}
