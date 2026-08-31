import {
  ArrowLeft,
  Bell,
  CaretRight,
  Code,
  CreditCard,
  Cube,
  DiscordLogo,
  Folder,
  Gauge,
  GearSix,
  GithubLogo,
  Keyboard,
  Lightbulb,
  Lightning,
  Palette,
  Plugs,
  Robot,
  SlackLogo,
  Terminal,
  TrafficSignal,
  TreeStructure,
  Wrench,
} from "@phosphor-icons/react";
import { Input, MenuLabel } from "@posthog/quill";
import { BILLING_FLAG } from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useQuickAskAvailable } from "@posthog/ui/features/quick-ask/useQuickAskAvailable";
import { SettingsPageContent } from "@posthog/ui/features/settings/components/SettingsPageContent";
import { closeSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import {
  type SettingsSearchEntry,
  searchSettings,
} from "@posthog/ui/features/settings/settingsSearch";
import { getHiddenSettingsCategories } from "@posthog/ui/features/settings/settingsVisibility";
import { useSettingsPageStore } from "@posthog/ui/features/settings/stores/settingsPageStore";
import {
  SETTINGS_PAGE_LABELS,
  type SettingsCategory,
} from "@posthog/ui/features/settings/types";
import { ProjectSwitcher } from "@posthog/ui/features/sidebar/components/ProjectSwitcher";
import { useSpendAnalysisEnabled } from "@posthog/ui/features/usage/useSpendAnalysisEnabled";
import * as nav from "@posthog/ui/router/navigationBridge";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { type ReactNode, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";

interface SidebarItem {
  id: SettingsCategory;
  icon: ReactNode;
  hasChevron?: boolean;
}

interface SidebarGroup {
  label: string;
  items: SidebarItem[];
}

// Grouped by the question being asked: how the app behaves, where code
// lives, what agents can do, what's connected. Page names come from
// SETTINGS_PAGE_LABELS, keyed by id.
const SIDEBAR_GROUPS: SidebarGroup[] = [
  {
    label: "App",
    items: [
      { id: "general", icon: <GearSix size={16} /> },
      { id: "notifications", icon: <Bell size={16} /> },
      { id: "personalization", icon: <Palette size={16} /> },
      { id: "shortcuts", icon: <Keyboard size={16} /> },
      { id: "quick-ask", icon: <Lightning size={16} /> },
    ],
  },
  {
    label: "Account",
    items: [
      { id: "plan-usage", icon: <CreditCard size={16} /> },
      { id: "cost-management", icon: <Gauge size={16} /> },
    ],
  },
  {
    label: "Code",
    items: [
      { id: "workspaces", icon: <Folder size={16} /> },
      { id: "worktrees", icon: <TreeStructure size={16} /> },
      { id: "environments", icon: <Cube size={16} /> },
      { id: "terminal", icon: <Terminal size={16} /> },
    ],
  },
  {
    label: "Agents",
    items: [
      { id: "agents", icon: <Robot size={16} /> },
      { id: "signals", icon: <TrafficSignal size={16} /> },
      { id: "skills", icon: <Lightbulb size={16} /> },
      { id: "mcp-servers", icon: <Plugs size={16} /> },
      { id: "harness", icon: <Code size={16} /> },
    ],
  },
  {
    label: "Connections",
    items: [
      { id: "github", icon: <GithubLogo size={16} /> },
      { id: "slack", icon: <SlackLogo size={16} /> },
      { id: "discord", icon: <DiscordLogo size={16} /> },
    ],
  },
  {
    label: "System",
    items: [{ id: "advanced", icon: <Wrench size={16} /> }],
  },
];

const SIDEBAR_ITEMS = SIDEBAR_GROUPS.flatMap((group) => group.items);

export interface SettingsPanelProps {
  /**
   * Override the active category. Defaults to the `$category` URL param
   * (which is what every in-app entry point uses). Provided for the
   * pre-router `ConsentScreen` shell where RouterProvider isn't mounted.
   */
  activeCategory?: SettingsCategory;
  /** Override the close handler. Defaults to router history back. */
  onClose?: () => void;
  /** Override the category-change handler. Defaults to router navigation. */
  onCategoryChange?: (category: SettingsCategory) => void;
}

export function SettingsPanel({
  activeCategory: activeCategoryProp,
  onClose,
  onCategoryChange,
}: SettingsPanelProps = {}) {
  const formMode = useSettingsPageStore((s) => s.formMode);
  const activeCategory = activeCategoryProp ?? "general";
  const [searchQuery, setSearchQuery] = useState("");
  const close = onClose ?? closeSettings;
  const setCategory =
    onCategoryChange ??
    ((cat: SettingsCategory) => nav.navigateToSettings(cat, { replace: true }));
  const isAuthenticated = useAuthStateValue(
    (state) => state.status === "authenticated",
  );
  const client = useOptionalAuthenticatedClient();
  const { data: user } = useCurrentUser({ client });
  const billingEnabled = useFeatureFlag(BILLING_FLAG);
  const { localWorkspaces } = useHostCapabilities();
  const quickAskAvailable = useQuickAskAvailable();

  const spendAnalysisEnabled = useSpendAnalysisEnabled();
  const hiddenCategories = getHiddenSettingsCategories({
    billingEnabled,
    spendAnalysisEnabled,
    localWorkspaces,
    quickAskAvailable,
  });
  const sidebarGroups = SIDEBAR_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !hiddenCategories.has(item.id)),
  })).filter((group) => group.items.length > 0);
  const searchResults = searchSettings(searchQuery, hiddenCategories);

  // Guard direct navigation (URL, deep link, programmatic openSettings) to a
  // category hidden on this host. Fall back to General so a hidden section is
  // never rendered.
  const resolvedCategory: SettingsCategory = hiddenCategories.has(
    activeCategory,
  )
    ? "general"
    : activeCategory;
  const activeSidebarCategory: SettingsCategory =
    resolvedCategory === "cloud-environments"
      ? "environments"
      : resolvedCategory;

  useHotkeys("escape", close, {
    enabled: true,
    enableOnContentEditable: true,
    enableOnFormTags: true,
    preventDefault: true,
  });

  const activeCategoryIcon = SIDEBAR_ITEMS.find(
    (item) => item.id === activeSidebarCategory,
  )?.icon;

  return (
    <div className="flex h-full w-full bg-background" data-page="settings">
      <div className="flex h-full w-[256px] shrink-0 flex-col border-border border-r bg-chrome">
        <div className="drag h-[36px] shrink-0 border-b border-b-border" />

        {isAuthenticated && user && (
          <div className="flex h-14 items-center gap-3 border-b border-b-border px-3">
            <UserAvatar user={user} />
            <div className="flex min-w-0 flex-col">
              <span className="truncate font-medium text-sm">{user.email}</span>
            </div>
          </div>
        )}

        <button
          type="button"
          className="mt-2 flex cursor-pointer items-center gap-2 border-0 bg-transparent px-3 py-2 text-left text-[13px] text-foreground transition-colors hover:bg-fill-hover"
          onClick={close}
        >
          <ArrowLeft size={14} />
          <span>Back to app</span>
        </button>

        <SettingsSearchInput
          query={searchQuery}
          onQueryChange={setSearchQuery}
          onSubmit={() => {
            const first = searchResults[0];
            if (first) {
              setCategory(first.category);
              setSearchQuery("");
            }
          }}
        />

        <div className="flex-1 overflow-y-auto [scrollbar-gutter:stable]">
          {searchQuery.trim() ? (
            <SettingsSearchResults
              results={searchResults}
              onSelect={(category) => {
                setCategory(category);
                setSearchQuery("");
              }}
            />
          ) : (
            <div className="flex flex-col gap-3 py-2">
              {sidebarGroups.map((group) => (
                <div key={group.label}>
                  <MenuLabel className="px-3 pb-1 text-muted-foreground">
                    {group.label}
                  </MenuLabel>
                  {group.items.map((item) => {
                    const isActive = activeSidebarCategory === item.id;
                    return (
                      <SidebarNavItem
                        key={item.id}
                        item={item}
                        isActive={isActive}
                        onClick={() => setCategory(item.id)}
                      />
                    );
                  })}
                </div>
              ))}
            </div>
          )}
        </div>

        {isAuthenticated && (
          <div className="border-border border-t p-2">
            <ProjectSwitcher onNavigateToSettings={setCategory} />
          </div>
        )}
      </div>

      <div className="relative flex flex-1 flex-col overflow-hidden">
        <div className="drag h-[36px] shrink-0 border-b border-b-border" />
        <div className="relative flex flex-1 justify-center overflow-hidden">
          <svg
            aria-hidden="true"
            style={{
              maskImage: "linear-gradient(to top, black 0%, transparent 100%)",
              WebkitMaskImage:
                "linear-gradient(to top, black 0%, transparent 100%)",
            }}
            className="pointer-events-none absolute bottom-0 left-0 h-full w-full opacity-40"
          >
            <defs>
              <pattern
                id="settings-dot-pattern"
                patternUnits="userSpaceOnUse"
                width="8"
                height="8"
              >
                <circle cx="0" cy="0" r="1" fill="var(--gray-6)" />
                <circle cx="0" cy="8" r="1" fill="var(--gray-6)" />
                <circle cx="8" cy="8" r="1" fill="var(--gray-6)" />
                <circle cx="8" cy="0" r="1" fill="var(--gray-6)" />
                <circle cx="4" cy="4" r="1" fill="var(--gray-6)" />
              </pattern>
            </defs>
            <rect
              width="100%"
              height="100%"
              fill="url(#settings-dot-pattern)"
            />
          </svg>
          <SettingsPageContent
            category={resolvedCategory}
            formMode={formMode}
            icon={activeCategoryIcon}
          />
        </div>
      </div>
    </div>
  );
}

function SettingsSearchInput({
  query,
  onQueryChange,
  onSubmit,
}: {
  query: string;
  onQueryChange: (query: string) => void;
  onSubmit: () => void;
}) {
  return (
    <div className="px-3 py-2">
      <Input
        value={query}
        onChange={(e) => onQueryChange(e.currentTarget.value)}
        onKeyDown={(e) => {
          // Escape clears the query before the panel-level hotkey can close
          // settings; a second Escape (empty query) closes as usual.
          if (e.key === "Escape" && query) {
            e.preventDefault();
            e.stopPropagation();
            onQueryChange("");
          }
          if (e.key === "Enter") {
            e.preventDefault();
            onSubmit();
          }
        }}
        placeholder="Search settings..."
        aria-label="Search settings"
        className="h-7 text-[13px] hover:bg-fill-hover"
      />
    </div>
  );
}

function SettingsSearchResults({
  results,
  onSelect,
}: {
  results: SettingsSearchEntry[];
  onSelect: (category: SettingsCategory) => void;
}) {
  if (results.length === 0) {
    return (
      <p className="m-0 px-3 py-2 text-[12.5px] text-muted-foreground">
        No settings match. Try another word, like "sound" or "theme".
      </p>
    );
  }

  return (
    <div className="flex flex-col py-1">
      {results.map((result) => (
        <button
          key={`${result.category}:${result.label}`}
          type="button"
          className="flex w-full cursor-pointer items-center justify-between gap-2 border-0 bg-transparent px-3 py-1.5 text-left transition-colors hover:bg-fill-hover"
          onClick={() => onSelect(result.category)}
        >
          <span className="min-w-0 truncate text-[13px] text-foreground">
            {result.label}
          </span>
          <span className="shrink-0 text-[11px] text-muted-foreground">
            {SETTINGS_PAGE_LABELS[result.category]}
          </span>
        </button>
      ))}
    </div>
  );
}

interface SidebarNavItemProps {
  item: SidebarItem;
  isActive: boolean;
  onClick: () => void;
}

function SidebarNavItem({ item, isActive, onClick }: SidebarNavItemProps) {
  return (
    <button
      type="button"
      className="flex w-full cursor-pointer items-center justify-between gap-2 border-0 bg-transparent px-3 py-1.5 text-left text-[13px] text-foreground transition-colors hover:bg-fill-hover data-[active]:bg-fill-selected"
      data-active={isActive || undefined}
      onClick={onClick}
    >
      <span className="flex items-center gap-2">
        <span className="text-muted-foreground">{item.icon}</span>
        <span>{SETTINGS_PAGE_LABELS[item.id]}</span>
      </span>
      {item.hasChevron && (
        <CaretRight size={12} className="text-muted-foreground" />
      )}
    </button>
  );
}
