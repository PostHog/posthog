import {
  BellIcon,
  BookOpenTextIcon,
  EnvelopeSimple,
  HouseSimple,
  type IconProps,
  Lightning,
} from "@phosphor-icons/react";
import type { RailVisit } from "@posthog/shared";
import type { SidebarNavItem } from "@posthog/shared/analytics-events";
import { readMirror } from "@posthog/ui/features/browser-tabs/tabsSync";
import { SpacesIcon } from "@posthog/ui/features/canvas/components/SpacesIcon";
import type { NavRailPane } from "@posthog/ui/features/canvas/railPane";
import {
  applyTabViewState,
  showChannelList,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import type { CountBadgeTone } from "@posthog/ui/primitives/CountBadge";
import { LoopIcon } from "@posthog/ui/primitives/LoopIcon";
import {
  navigateToActivity,
  navigateToChannel,
  navigateToCommandCenter,
  navigateToHome,
  navigateToInbox,
  navigateToLoops,
  navigateToSpaces,
  navigateToSpacesContext,
} from "@posthog/ui/router/navigationBridge";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import type { ComponentType } from "react";

export interface RailCounts {
  inbox: number;
  activity: number;
  commandCenter: number;
}

export interface RailDestination {
  pane: NavRailPane;
  label: string;
  analyticsId: SidebarNavItem;
  Icon: ComponentType<IconProps>;
  /** Root opened by an explicit Cmd/Ctrl-click. */
  href: string;
  /** Where the destination lands with nothing remembered. */
  onPick: () => void;
  /**
   * What a click on the destination you are already on does, when that differs
   * from landing on its root. Defaults to `onPick`.
   */
  onReclick?: () => void;
  shortcut?: string;
  count?: (counts: RailCounts) => number;
  countTone?: CountBadgeTone;
  enabled?: (flags: {
    home: boolean;
    inbox: boolean;
    loops: boolean;
    context: boolean;
  }) => boolean;
}

/**
 * Show the space tree. Which space you are in is unchanged — browsing the list
 * is view state — but the destinations that own the whole screen have no column
 * to put it in, so leaving one is part of the pick.
 */
export function showSpaces(): void {
  const channelId = useCurrentChannelStore.getState().currentChannelId;
  if (!channelId) {
    showChannelList();
    navigateToSpaces();
    return;
  }
  showChannelList({ keepForRoute: channelId });
  navigateToChannel(channelId);
}

/**
 * Where each rail destination was when the ACTIVE TAB last left it. Per tab, so
 * a pick in one tab can never restore an href another tab established, and so
 * two tabs can sit on the same destination in different places.
 */
function lastVisitForActiveTab(pane: NavRailPane): RailVisit | undefined {
  const snapshot = readMirror();
  const window =
    snapshot.windows.find((w) => w.isPrimary) ?? snapshot.windows[0];
  const active = window?.activeTabId
    ? snapshot.tabs.find((t) => t.id === window.activeTabId)
    : undefined;
  return active?.viewState?.lastByPane?.[pane];
}

function currentHref(): string | undefined {
  const state = getRouterOrNull()?.state;
  return (state?.resolvedLocation ?? state?.location)?.href;
}

/**
 * Put a destination back the way you left it, sidebar pane included. Shares
 * `applyTabViewState` with the tab switch, which restores the same two facts:
 * an unscoped space route (the index, an unfiled task) has no channel to hold
 * the list across, but the list was open and stays open.
 */
function restoreVisit(visit: RailVisit): void {
  applyTabViewState(visit);
  void getRouterOrNull()?.navigate({ href: visit.href });
}

/**
 * Act on a rail click: return to where the destination was, or land on its root
 * when there is nothing to return to. Clicking the destination you are already
 * on never restores — you are looking at it.
 */
export function pickRailDestination(
  destination: RailDestination,
  current: NavRailPane,
): void {
  if (destination.pane === current) {
    (destination.onReclick ?? destination.onPick)();
    return;
  }
  const visit = lastVisitForActiveTab(destination.pane);
  // A remembered visit that IS where we already are restores nothing, and the
  // click would look dead. Fall through to the destination's root instead, so
  // a pick always goes somewhere.
  if (visit && visit.href !== currentHref()) restoreVisit(visit);
  else destination.onPick();
}

export const RAIL_DESTINATIONS: readonly RailDestination[] = [
  {
    pane: "home",
    label: "Home",
    analyticsId: "home",
    Icon: HouseSimple,
    href: "/",
    onPick: navigateToHome,
    enabled: (flags) => flags.home,
  },
  {
    pane: "spaces",
    label: "Spaces",
    analyticsId: "spaces",
    Icon: SpacesIcon,
    href: "/spaces",
    onPick: showSpaces,
    // Already in Spaces, so the pick is asking for the one thing above the
    // space you are in: the list.
    onReclick: showChannelList,
  },
  {
    pane: "activity",
    label: "Activity",
    analyticsId: "activity",
    Icon: BellIcon,
    href: "/activity",
    onPick: navigateToActivity,
    count: (counts) => counts.activity,
  },
  {
    pane: "inbox",
    label: "Self-driving",
    analyticsId: "inbox",
    Icon: EnvelopeSimple,
    href: "/inbox",
    onPick: navigateToInbox,
    shortcut: formatHotkey(SHORTCUTS.INBOX),
    count: (counts) => counts.inbox,
    enabled: (flags) => flags.inbox,
  },
  {
    pane: "command-center",
    label: "Command Center",
    analyticsId: "command_center",
    Icon: Lightning,
    href: "/command-center",
    onPick: navigateToCommandCenter,
    count: (counts) => counts.commandCenter,
    countTone: "neutral",
  },
  {
    pane: "loops",
    label: "Loops",
    analyticsId: "loops",
    Icon: LoopIcon,
    href: "/loops",
    onPick: () => navigateToLoops(),
    enabled: (flags) => flags.loops,
  },
  {
    pane: "context",
    label: "Context",
    analyticsId: "contexts",
    Icon: BookOpenTextIcon,
    href: "/spaces/context",
    onPick: navigateToSpacesContext,
    enabled: (flags) => flags.context,
  },
];

export function visibleRailDestinations(flags: {
  home: boolean;
  inbox: boolean;
  loops: boolean;
  context: boolean;
}): readonly RailDestination[] {
  return RAIL_DESTINATIONS.filter(({ enabled }) => enabled?.(flags) ?? true);
}
