import {
  BellIcon,
  DotsThree,
  GearSix,
  MagnifyingGlass,
} from "@phosphor-icons/react";
import {
  Button,
  cn,
  Kbd,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import {
  DESKTOP_HOME_FLAG,
  LOOPS_FLAG,
  SAVED_SEARCHES_RAIL_FLAG,
} from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useOpenBrowserTab } from "@posthog/ui/features/browser-tabs/useOpenBrowserTab";
import { useSpacesTabs } from "@posthog/ui/features/browser-tabs/useSpacesTabs";
import { ActivityHoverCard } from "@posthog/ui/features/canvas/components/ActivityHoverCard";
import { ChannelsFab } from "@posthog/ui/features/canvas/components/ChannelsFab";
import {
  pickRailDestination,
  type RailCounts,
  type RailDestination,
  showWorkColumn,
  visibleRailDestinations,
  visibleWorkRailDestinations,
} from "@posthog/ui/features/canvas/components/railDestinations";
import { useProjectTaskFeeds } from "@posthog/ui/features/canvas/hooks/useProjectTaskFeeds";
import { useRailPane } from "@posthog/ui/features/canvas/hooks/useRailSurface";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useWorkLayout } from "@posthog/ui/features/canvas/hooks/useWorkLayout";
import {
  type NavRailPane,
  railPaneFoldsIntoWork,
} from "@posthog/ui/features/canvas/railPane";
import { useActivityFilterStore } from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import {
  closeWorkActivity,
  useWorkActivityStore,
} from "@posthog/ui/features/canvas/stores/workActivityStore";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { useCommandCenterActiveCount } from "@posthog/ui/features/command-center/useCommandCenterActiveCount";
import { useContextLayerFlag } from "@posthog/ui/features/feature-flags/useContextLayerFlag";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useInboxAvailable } from "@posthog/ui/features/feature-flags/useInboxAvailable";
import { useInboxDecisionCount } from "@posthog/ui/features/inbox/hooks/useInboxDecisionCount";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { NavRailTile } from "@posthog/ui/features/sidebar/components/NavRailTile";
import { ProjectSwitcher } from "@posthog/ui/features/sidebar/components/ProjectSwitcher";
import { useNavRailMetrics } from "@posthog/ui/features/sidebar/navRailSize";
import { CountBadge } from "@posthog/ui/primitives/CountBadge";
import { track } from "@posthog/ui/shell/analytics";
import { useCommandMenuStore } from "@posthog/ui/shell/commandMenuStore";
import {
  type ComponentPropsWithRef,
  type MouseEvent,
  type MouseEventHandler,
  memo,
  type ReactElement,
  type ReactNode,
  useState,
} from "react";

const ICON_BADGE_CLASS =
  "-top-1 -right-1 absolute h-3.5 min-w-3.5 w-auto px-1 font-semibold text-[9px] ring-2 ring-chrome";

function NotificationDot() {
  return (
    <span
      data-slot="dot"
      className="absolute top-0 right-0 size-2 rounded-full bg-primary ring-2 ring-chrome"
      aria-hidden
    />
  );
}

function NavIcon({
  icon,
  label,
  caption,
  shortcut,
  isActive,
  onClick,
  badge,
}: {
  icon: ReactNode;
  label: string;
  caption?: string;
  shortcut?: string;
  isActive: boolean;
  onClick: MouseEventHandler<HTMLButtonElement>;
  badge?: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <NavButton
            icon={icon}
            label={label}
            caption={caption}
            isActive={isActive}
            onClick={onClick}
            badge={badge}
          />
        }
      />
      <TooltipContent side="right" alignOffset={-10}>
        {label}
        {shortcut && <Kbd>{shortcut}</Kbd>}
      </TooltipContent>
    </Tooltip>
  );
}

interface NavButtonProps extends ComponentPropsWithRef<"button"> {
  icon: ReactNode;
  label: string;
  caption?: string;
  isActive: boolean;
  badge?: ReactNode;
}

function NavButton({
  icon,
  label,
  caption,
  isActive,
  badge,
  ...buttonProps
}: NavButtonProps) {
  return (
    <NavRailTile
      {...buttonProps}
      aria-label={label}
      caption={caption ?? label}
      data-selected={isActive || undefined}
    >
      {icon}
      {badge}
    </NavRailTile>
  );
}

function ActivityHoverPopover({ trigger }: { trigger: ReactElement }) {
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        openOnHover
        delay={300}
        closeDelay={100}
        onClick={(event) => event.preventBaseUIHandler()}
        render={trigger}
      />
      {open && (
        <ActivityHoverCard side="right" onClose={() => setOpen(false)} />
      )}
    </Popover>
  );
}

function MoreNavItem({
  destinations,
  railPane,
  counts,
  onPick,
}: {
  destinations: readonly RailDestination[];
  railPane: NavRailPane;
  counts: RailCounts;
  onPick: (
    destination: RailDestination,
  ) => (event: MouseEvent<HTMLElement>) => void;
}) {
  const { iconSize } = useNavRailMetrics();
  const [open, setOpen] = useState(false);
  const isActive = destinations.some(({ pane }) => pane === railPane);
  const hasCount = destinations.some(({ count }) => (count?.(counts) ?? 0) > 0);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        openOnHover
        delay={150}
        closeDelay={100}
        render={
          <NavButton
            icon={<DotsThree size={iconSize} weight="bold" />}
            label="More"
            isActive={isActive || open}
            badge={hasCount ? <NotificationDot /> : null}
          />
        }
      />
      <PopoverContent
        side="right"
        align="start"
        sideOffset={8}
        className="w-52 gap-0.5 p-1"
      >
        {destinations.map((destination) => {
          const { pane, label, Icon, count, countTone } = destination;
          const pick = onPick(destination);
          return (
            <Button
              key={pane}
              variant="default"
              size="sm"
              data-selected={railPane === pane || undefined}
              className="w-full justify-start data-selected:bg-fill-selected"
              onClick={(event) => {
                setOpen(false);
                pick(event);
              }}
            >
              <Icon size={16} weight={railPane === pane ? "fill" : "regular"} />
              {label}
              <CountBadge
                count={count?.(counts) ?? 0}
                tone={countTone}
                className="ml-auto"
              />
            </Button>
          );
        })}
      </PopoverContent>
    </Popover>
  );
}

// No peek once Activity is the destination: the feed is already beside you.
function ActivityNavItem({
  isActive,
  badge,
  onClick,
}: {
  isActive: boolean;
  badge: ReactNode;
  onClick: MouseEventHandler<HTMLButtonElement>;
}) {
  const { iconSize } = useNavRailMetrics();
  const bell = (
    <NavButton
      icon={<BellIcon size={iconSize} weight={isActive ? "fill" : "regular"} />}
      label="Activity"
      isActive={isActive}
      onClick={onClick}
      badge={badge}
    />
  );

  if (isActive) return bell;
  return <ActivityHoverPopover trigger={bell} />;
}

/**
 * The app's leftmost column. Sits outside the resizable sidebar, so collapsing
 * that sidebar leaves the destinations reachable.
 */
function NavRailImpl() {
  const { width, iconSize, gapClassName } = useNavRailMetrics();
  const homeEnabled = useFeatureFlag(DESKTOP_HOME_FLAG);
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG);
  const contextEnabled = useContextLayerFlag();
  const inboxAvailable = useInboxAvailable();
  const tabsEnabled = useSpacesTabs();
  const openBrowserTab = useOpenBrowserTab();
  const mentionsEnabled = useActivityFilterStore(
    (state) => state.mentionsEnabled,
  );

  const savedSearchesRailEnabled = useFeatureFlag(SAVED_SEARCHES_RAIL_FLAG);
  const hasSavedSearches = useProjectTaskFeeds().length > 0;
  const workLayout = useWorkLayout();
  const workActivityOpen = useWorkActivityStore((state) => state.open);
  const toggleWorkActivity = useWorkActivityStore((state) => state.toggle);
  const railFlags = {
    home: homeEnabled,
    inbox: inboxAvailable,
    loops: loopsEnabled,
    context: contextEnabled,
    savedSearches: savedSearchesRailEnabled && hasSavedSearches,
  };
  const destinations = workLayout
    ? visibleWorkRailDestinations(railFlags)
    : visibleRailDestinations(railFlags);
  const topDestinations = destinations.filter(
    ({ placement }) => placement === undefined || placement === "top",
  );
  const moreDestinations = destinations.filter(
    ({ placement }) => placement === "more",
  );
  const bottomDestinations = destinations.filter(
    ({ placement }) => placement === "bottom",
  );
  const inboxVisible = destinations.some(({ pane }) => pane === "inbox");
  const inboxDecisionCount = useInboxDecisionCount({
    enabled: inboxVisible,
    ignoreFilters: true,
  });
  const { unreadCount: unseenActivity } = useTaskActivity({
    enabled: mentionsEnabled,
  });
  const commandCenterCount = useCommandCenterActiveCount();
  const counts: RailCounts = {
    inbox: inboxDecisionCount,
    activity: mentionsEnabled ? unseenActivity : 0,
    commandCenter: commandCenterCount,
  };
  // The route is the only thing that says where you are, so the rail cannot
  // light a destination the screen isn't on.
  const railPane = useRailPane();
  const toggleCommandMenu = useCommandMenuStore((s) => s.toggle);
  // So the create button files into the space you are in, like the shortcut.
  const currentChannelId = useCurrentChannelStore((s) => s.currentChannelId);

  const pick =
    (destination: RailDestination) =>
    (event: MouseEvent<HTMLElement>): void => {
      track(ANALYTICS_EVENTS.SIDEBAR_NAV_ITEM_CLICKED, {
        item: destination.analyticsId,
        in_more: destination.placement === "more",
        layout: "channels",
      });
      if (tabsEnabled && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        openBrowserTab(destination.href);
        return;
      }
      if (workLayout) {
        if (destination.pane === "activity") {
          if (!workActivityOpen) showWorkColumn();
          toggleWorkActivity();
          return;
        }
        closeWorkActivity();
        if (destination.pane === "spaces" && railPaneFoldsIntoWork(railPane)) {
          showWorkColumn();
          return;
        }
      }
      pickRailDestination(destination, railPane);
    };

  const renderDestination = (destination: RailDestination): ReactNode => {
    const { pane, label, Icon, count, countTone } = destination;
    const isActive = workLayout
      ? pane === "activity"
        ? workActivityOpen
        : pane === "spaces"
          ? !workActivityOpen && railPaneFoldsIntoWork(railPane)
          : !workActivityOpen && railPane === pane
      : railPane === pane;
    const destinationCount = count?.(counts) ?? 0;
    const usesNotificationDot = pane === "activity" || pane === "inbox";
    let badge: ReactNode;
    if (usesNotificationDot) {
      badge = destinationCount > 0 ? <NotificationDot /> : null;
    } else {
      badge = (
        <CountBadge
          count={destinationCount}
          tone={countTone}
          className={ICON_BADGE_CLASS}
        />
      );
    }
    const onClick = pick(destination);

    if (pane === "activity") {
      return (
        <ActivityNavItem
          key={pane}
          isActive={isActive}
          badge={badge}
          onClick={onClick}
        />
      );
    }
    return (
      <NavIcon
        key={pane}
        icon={
          <Icon
            size={pane === "spaces" && !workLayout ? iconSize + 4 : iconSize}
            weight={isActive ? "fill" : "regular"}
          />
        }
        label={label}
        caption={destination.shortLabel}
        shortcut={destination.shortcut}
        isActive={isActive}
        onClick={onClick}
        badge={badge}
      />
    );
  };

  return (
    // One provider for the whole rail: the tooltip skip window is provider
    // state, so isolated providers never share it.
    <TooltipProvider delay={400}>
      <div
        data-testid="nav-rail"
        className={cn(
          "relative z-[60] flex h-full shrink-0 flex-col items-center overflow-y-auto overflow-x-hidden bg-chrome px-1 pt-1 pb-2 [scrollbar-width:none]",
          gapClassName,
        )}
        style={{ width }}
      >
        {topDestinations.map(renderDestination)}
        {moreDestinations.length > 0 && (
          <MoreNavItem
            destinations={moreDestinations}
            railPane={railPane}
            counts={counts}
            onPick={pick}
          />
        )}
        <div
          className={cn(
            "mt-auto flex w-full flex-col items-center",
            gapClassName,
          )}
        >
          {bottomDestinations.map(renderDestination)}
          {/* Every destination keeps the rail, sidebar or not, so the create
              button is reachable from all of them here. */}
          <ChannelsFab
            channelId={currentChannelId ?? undefined}
            placement="rail"
          />
          <NavIcon
            icon={<MagnifyingGlass size={iconSize} />}
            label="Search"
            shortcut={formatHotkey(SHORTCUTS.COMMAND_MENU)}
            isActive={false}
            onClick={() => {
              track(ANALYTICS_EVENTS.SIDEBAR_NAV_ITEM_CLICKED, {
                item: "search",
                in_more: false,
                layout: "channels",
              });
              toggleCommandMenu();
            }}
          />
          <NavIcon
            icon={<GearSix size={iconSize} />}
            label="Settings"
            shortcut={formatHotkey(SHORTCUTS.SETTINGS)}
            isActive={false}
            onClick={() => {
              track(ANALYTICS_EVENTS.SIDEBAR_NAV_ITEM_CLICKED, {
                item: "configure",
                in_more: false,
                layout: "channels",
              });
              openSettings();
            }}
          />
          <ProjectSwitcher appearance="icon" />
        </div>
      </div>
    </TooltipProvider>
  );
}

// The root layout re-renders on every navigation; this keeps that from cascading here.
export const NavRail = memo(NavRailImpl);
