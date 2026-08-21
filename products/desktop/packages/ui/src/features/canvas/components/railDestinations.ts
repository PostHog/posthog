import {
  BellIcon,
  EnvelopeSimple,
  HouseSimple,
  type IconProps,
  Lightning,
} from "@phosphor-icons/react";
import type { SidebarNavItem } from "@posthog/shared/analytics-events";
import { SpacesIcon } from "@posthog/ui/features/canvas/components/SpacesIcon";
import { showChannelList } from "@posthog/ui/features/canvas/stores/channelPaneStore";
import type { NavRailPane } from "@posthog/ui/features/canvas/stores/navRailStore";
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
  navigateToHome,
  navigateToInbox,
  navigateToLoops,
  navigateToWebsiteCommandCenter,
} from "@posthog/ui/router/navigationBridge";
import type { AppViewType } from "@posthog/ui/router/useAppView";
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
  viewTypes: readonly AppViewType[];
  onPick?: (ctx: { inWebsiteTree: boolean }) => void;
  customizableId?: CustomizableNavItemId;
  shortcut?: string;
  count?: (counts: RailCounts) => number;
  countTone?: CountBadgeTone;
  enabled?: (flags: { loops: boolean }) => boolean;
}

export const RAIL_DESTINATIONS: readonly RailDestination[] = [
  {
    pane: "home",
    label: "Home",
    analyticsId: "home",
    Icon: HouseSimple,
    viewTypes: ["home"],
    onPick: navigateToHome,
  },
  {
    pane: "spaces",
    label: "Spaces",
    analyticsId: "spaces",
    Icon: SpacesIcon,
    viewTypes: [],
    onPick: showChannelList,
  },
  {
    pane: "activity",
    customizableId: "activity",
    label: "Activity",
    analyticsId: "activity",
    Icon: BellIcon,
    viewTypes: ["activity"],
    onPick: ({ inWebsiteTree }) => {
      if (!inWebsiteTree) navigateToActivity();
    },
    count: (counts) => counts.activity,
  },
  {
    pane: "inbox",
    customizableId: "inbox",
    label: "Inbox",
    analyticsId: "inbox",
    Icon: EnvelopeSimple,
    viewTypes: ["inbox"],
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
    viewTypes: ["command-center"],
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
    viewTypes: ["loops"],
    onPick: () => navigateToLoops(),
    enabled: (flags) => flags.loops,
  },
];

const PANE_BY_VIEW_TYPE = new Map<AppViewType, NavRailPane>(
  RAIL_DESTINATIONS.flatMap((destination) =>
    destination.viewTypes.map((viewType) => [viewType, destination.pane]),
  ),
);

/** Which destination a route belongs to. Unclaimed routes belong to Spaces. */
export function paneForView(viewType: AppViewType): NavRailPane {
  return PANE_BY_VIEW_TYPE.get(viewType) ?? "spaces";
}

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
