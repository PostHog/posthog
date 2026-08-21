import {
  BellIcon,
  EnvelopeSimple,
  HouseSimple,
  type IconProps,
  Lightning,
  SquaresFourIcon,
} from "@phosphor-icons/react";
import type { SidebarNavItem } from "@posthog/shared/analytics-events";
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
  // Not phosphor's `Icon`: that is the forwardRef shape, and LoopIcon (a plain
  // wrapper over RepeatIcon) does not have it.
  Icon: ComponentType<IconProps>;
  /**
   * The app views that belong here, so a deep link, a back button or a ⌘1-9
   * jump lights the entry the rail would have. Everything not claimed belongs
   * to Spaces — a channel, a task and a new-task screen are all reached
   * through its tree.
   */
  viewTypes: readonly AppViewType[];
  /**
   * What picking it does beyond selecting the pane. Spaces and Activity draw
   * into the content pane the /website layout owns; from inside that tree they
   * move nothing, which is what lets Spaces put you back on the screen
   * Activity was covering.
   */
  onPick?: (ctx: { inWebsiteTree: boolean }) => void;
  /**
   * The id this destination is customized under, when it is one a user can
   * hide or reorder from the sidebar settings. Home and Spaces are not: they
   * own the column beside the rail, so hiding them would strand it.
   */
  customizableId?: CustomizableNavItemId;
  shortcut?: string;
  count?: (counts: RailCounts) => number;
  countTone?: CountBadgeTone;
  enabled?: (flags: { loops: boolean }) => boolean;
}

/**
 * Every destination the rail offers, top to bottom.
 *
 * One table rather than one JSX block each: the entries differ only in these
 * fields, and written out longhand the pane comparison appeared twice per item
 * and the route mapping had to be maintained as a second, separate switch that
 * could silently disagree with it.
 */
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
    Icon: SquaresFourIcon,
    // Everything unclaimed lands here, so the tree needs no view types of its
    // own — see `paneForView`.
    viewTypes: [],
    // Always the list, even from inside a space: this is the entry to the
    // tree, and the space you were in stays scoped behind it.
    onPick: showChannelList,
  },
  {
    pane: "activity",
    customizableId: "activity",
    label: "Activity",
    analyticsId: "activity",
    Icon: BellIcon,
    viewTypes: ["activity"],
    // Inbox and Loops still live in /code. Picked from there, Activity would
    // have nowhere to draw — a dead feed beside the screen you were on.
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
    // Wrapped, not passed bare: it takes an options object, and handing it the
    // pick context would read as options it never meant to receive.
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

/**
 * The destinations to draw, in order, for a given set of user preferences.
 *
 * Hiding and reordering are the sidebar settings' feature, and the rail honors
 * both. It keeps its own default sequence rather than the shared
 * `orderedNavItems`, whose adjacency rule pins Activity below Inbox — the rail
 * puts Activity first. A stored drag order still wins over either.
 */
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
  // Only the customizable entries move; the pinned ones keep their slots.
  const result = [...shown];
  positions.forEach((position, i) => {
    result[position] = reordered[i];
  });
  return result;
}
