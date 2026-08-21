import {
  BellIcon,
  EnvelopeSimple,
  HouseSimple,
  type IconProps,
  Lightning,
} from "@phosphor-icons/react";
import type { SidebarNavItem } from "@posthog/shared/analytics-events";
import { SpacesIcon } from "@posthog/ui/features/canvas/components/SpacesIcon";
import {
  getRailPane,
  type NavRailPane,
} from "@posthog/ui/features/canvas/railPane";
import {
  keepListForRoute,
  showChannelList,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
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
  navigateToCanvas,
  navigateToChannel,
  navigateToHome,
  navigateToInbox,
  navigateToLoops,
  navigateToWebsiteCommandCenter,
} from "@posthog/ui/router/navigationBridge";
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
  /** Every pick routes. The rail's selected state is read back off the route,
   *  so a destination that changed nothing in the URL could never be left. */
  onPick: () => void;
  customizableId?: CustomizableNavItemId;
  shortcut?: string;
  count?: (counts: RailCounts) => number;
  countTone?: CountBadgeTone;
  enabled?: (flags: { loops: boolean }) => boolean;
}

/**
 * Show the space tree. Which space you are in is unchanged — browsing the list
 * is view state — but the destinations that own the whole screen have no column
 * to put it in, so leaving one is part of the pick.
 */
export function showSpaces(): void {
  showChannelList();
  if (getRailPane() === "spaces") return;

  const channelId = useCurrentChannelStore.getState().currentChannelId;
  if (!channelId) {
    navigateToCanvas();
    return;
  }
  // Arriving at a space pulls the slider to that space. This pick asked for the
  // list, so latch it across the navigation it is about to make.
  keepListForRoute(channelId);
  navigateToChannel(channelId);
}

export const RAIL_DESTINATIONS: readonly RailDestination[] = [
  {
    pane: "home",
    label: "Home",
    analyticsId: "home",
    Icon: HouseSimple,
    onPick: navigateToHome,
  },
  {
    pane: "spaces",
    label: "Spaces",
    analyticsId: "spaces",
    Icon: SpacesIcon,
    onPick: showSpaces,
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
    onPick: navigateToWebsiteCommandCenter,
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
];

// Deliberately not the shared `orderedNavItems`: its adjacency rule pins
// Activity below Inbox, and the rail puts Activity first.
export function visibleRailDestinations({
  overrides,
  order,
  loops,
}: {
  overrides: NavItemOverrides;
  order: readonly CustomizableNavItemId[];
  loops: boolean;
}): readonly RailDestination[] {
  const shown = RAIL_DESTINATIONS.filter(
    ({ customizableId, enabled }) =>
      (enabled?.({ loops }) ?? true) &&
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
