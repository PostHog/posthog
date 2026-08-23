import {
  BellIcon,
  BookOpenTextIcon,
  EnvelopeSimple,
  HouseSimple,
  type IconProps,
  Lightning,
} from "@phosphor-icons/react";
import type { SidebarNavItem } from "@posthog/shared/analytics-events";
import { SpacesIcon } from "@posthog/ui/features/canvas/components/SpacesIcon";
import type { NavRailPane } from "@posthog/ui/features/canvas/railPane";
import {
  showChannelList,
  showChannelPane,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import {
  type RailVisit,
  useRailHistoryStore,
} from "@posthog/ui/features/canvas/stores/railHistoryStore";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import {
  type CustomizableNavItemId,
  isNavItemVisible,
  type NavItemOverrides,
} from "@posthog/ui/features/sidebar/constants";
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
  /** Where the destination lands with nothing remembered. */
  onPick: () => void;
  /**
   * What a click on the destination you are already on does, when that differs
   * from landing on its root. Defaults to `onPick`.
   */
  onReclick?: () => void;
  customizableId?: CustomizableNavItemId;
  shortcut?: string;
  count?: (counts: RailCounts) => number;
  countTone?: CountBadgeTone;
  enabled?: (flags: {
    home: boolean;
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
  showChannelList(channelId);
  navigateToChannel(channelId);
}

/** Put a destination back the way you left it, sidebar pane included. */
function restoreVisit(visit: RailVisit): void {
  const spaces = visit.spaces;
  if (spaces) {
    if (!spaces.listOpen) showChannelPane();
    // An unscoped space route (the index, an unfiled task) has no channel to
    // hold the list across, but the list was open and stays open.
    else showChannelList(spaces.spaceId);
  }
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
  const visit = useRailHistoryStore.getState().lastByPane[destination.pane];
  if (visit) restoreVisit(visit);
  else destination.onPick();
}

export const RAIL_DESTINATIONS: readonly RailDestination[] = [
  {
    pane: "home",
    label: "Home",
    analyticsId: "home",
    Icon: HouseSimple,
    onPick: navigateToHome,
    enabled: (flags) => flags.home,
  },
  {
    pane: "spaces",
    label: "Spaces",
    analyticsId: "spaces",
    Icon: SpacesIcon,
    onPick: showSpaces,
    // Already in Spaces, so the pick is asking for the one thing above the
    // space you are in: the list.
    onReclick: showChannelList,
  },
  {
    pane: "activity",
    customizableId: "activity",
    label: "Activity",
    analyticsId: "activity",
    Icon: BellIcon,
    onPick: navigateToActivity,
    count: (counts) => counts.activity,
  },
  {
    pane: "inbox",
    customizableId: "inbox",
    label: "Inbox",
    analyticsId: "inbox",
    Icon: EnvelopeSimple,
    onPick: navigateToInbox,
    shortcut: formatHotkey(SHORTCUTS.INBOX),
    count: (counts) => counts.inbox,
  },
  {
    pane: "command-center",
    customizableId: "command-center",
    label: "Command Center",
    analyticsId: "command_center",
    Icon: Lightning,
    onPick: navigateToCommandCenter,
    count: (counts) => counts.commandCenter,
    countTone: "neutral",
  },
  {
    pane: "loops",
    customizableId: "loops",
    label: "Loops",
    analyticsId: "loops",
    Icon: LoopIcon,
    onPick: () => navigateToLoops(),
    enabled: (flags) => flags.loops,
  },
  {
    pane: "context",
    customizableId: "contexts",
    label: "Context",
    analyticsId: "contexts",
    Icon: BookOpenTextIcon,
    onPick: navigateToSpacesContext,
    enabled: (flags) => flags.context,
  },
];

// Deliberately not the shared `orderedNavItems`: its adjacency rule pins
// Activity below Inbox, and the rail puts Activity first.
export function visibleRailDestinations({
  overrides,
  order,
  home,
  loops,
  context,
}: {
  overrides: NavItemOverrides;
  order: readonly CustomizableNavItemId[];
  home: boolean;
  loops: boolean;
  context: boolean;
}): readonly RailDestination[] {
  const shown = RAIL_DESTINATIONS.filter(
    ({ customizableId, enabled }) =>
      (enabled?.({ home, loops, context }) ?? true) &&
      (!customizableId || isNavItemVisible(overrides, customizableId)),
  );
  if (order.length === 0) return shown;

  const rank = new Map(order.map((id, index) => [id, index]));
  const positions = shown
    .map((_, index) => index)
    .filter((index) => {
      const id = shown[index].customizableId;
      return id !== undefined && rank.has(id);
    });
  const reordered = positions
    .map((index) => shown[index])
    .sort(
      (a, b) =>
        (rank.get(a.customizableId as CustomizableNavItemId) ?? 0) -
        (rank.get(b.customizableId as CustomizableNavItemId) ?? 0),
    );
  const result = [...shown];
  positions.forEach((position, i) => {
    result[position] = reordered[i];
  });
  return result;
}
