import { BellIcon, GearSix } from "@phosphor-icons/react";
import {
  Button,
  cn,
  Kbd,
  Popover,
  PopoverTrigger,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { LOOPS_FLAG } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { ActivityHoverCard } from "@posthog/ui/features/canvas/components/ActivityHoverCard";
import {
  paneForView,
  type RailCounts,
  type RailDestination,
  visibleRailDestinations,
} from "@posthog/ui/features/canvas/components/railDestinations";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useNavRailStore } from "@posthog/ui/features/canvas/stores/navRailStore";
import { useCommandCenterActiveCount } from "@posthog/ui/features/command-center/useCommandCenterActiveCount";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { ProjectSwitcher } from "@posthog/ui/features/sidebar/components/ProjectSwitcher";
import {
  isNavItemVisible,
  NAV_RAIL_WIDTH,
} from "@posthog/ui/features/sidebar/constants";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { CountBadge } from "@posthog/ui/primitives/CountBadge";
import { useAppView } from "@posthog/ui/router/useAppView";
import { track } from "@posthog/ui/shell/analytics";
import { useRouterState } from "@tanstack/react-router";
import {
  type ComponentPropsWithRef,
  type ReactElement,
  type ReactNode,
  useEffect,
  useState,
} from "react";

const INBOX_REFETCH_INTERVAL_MS = 60_000;

const ICON_BADGE_CLASS =
  "-top-1 -right-1 absolute h-3.5 min-w-3.5 w-auto px-1 font-semibold text-[9px] ring-2 ring-chrome";

function NavIcon({
  icon,
  label,
  shortcut,
  isActive,
  onClick,
  badge,
}: {
  icon: ReactNode;
  label: string;
  shortcut?: string;
  isActive: boolean;
  onClick: () => void;
  badge?: ReactNode;
}) {
  return (
    <Tooltip>
      {/* quill's Button, with the sidebar's selected-row treatment — the same
          `data-selected` pairing the channel rows use, so the rail and the list
          beside it read as one control set in either theme. `relative` is for
          the count badge, which pins to the button's corner. */}
      <TooltipTrigger
        render={
          <Button
            variant="default"
            size="icon"
            aria-label={label}
            data-selected={isActive || undefined}
            onClick={onClick}
            className="group relative shrink-0 text-muted-foreground data-selected:bg-fill-selected data-selected:text-foreground"
          >
            {icon}
            {badge}
          </Button>
        }
      />
      <TooltipContent side="right">
        {label}
        {shortcut && <Kbd className="ml-1.5">{shortcut}</Kbd>}
      </TooltipContent>
    </Tooltip>
  );
}

interface NavButtonProps extends ComponentPropsWithRef<"button"> {
  icon: ReactNode;
  label: string;
  isActive: boolean;
  badge?: ReactNode;
}

// Same quill Button as NavIcon above — this variant only exists because the
// Activity entry is a Popover trigger, so it needs to forward the trigger's
// props and ref. Hand-rolling the button here left it a size larger than its
// neighbours.
function NavButton({
  icon,
  label,
  isActive,
  onClick,
  badge,
  className,
  ref,
  ...buttonProps
}: NavButtonProps) {
  return (
    <Button
      {...buttonProps}
      ref={ref}
      type="button"
      variant="default"
      size="icon"
      aria-label={label}
      data-selected={isActive || undefined}
      onClick={onClick}
      className={cn(
        "relative shrink-0 text-muted-foreground data-selected:bg-fill-selected data-selected:text-foreground",
        className,
      )}
    >
      {icon}
      {badge}
    </Button>
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

/**
 * The bell, with a peek at the feed on hover.
 *
 * The card is for reading the feed from wherever you are without giving up the
 * screen you are on. Once Activity is the destination the feed is already
 * beside you, so hovering its own entry would only cover it with a copy.
 */
function ActivityNavItem({
  isActive,
  badge,
  onClick,
}: {
  isActive: boolean;
  badge: ReactNode;
  onClick: () => void;
}) {
  const bell = (
    <NavButton
      icon={<BellIcon size={16} weight={isActive ? "fill" : "regular"} />}
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
 * The app's leftmost column: every destination as an icon, with the project
 * menu at its foot.
 *
 * It sits outside the resizable sidebar, so collapsing that sidebar leaves the
 * destinations reachable. Two of them own the column to the rail's right:
 * Spaces draws the channel tree, Activity draws the feed. Both are view state
 * rather than routes — picking them must not take you off the screen you are
 * on — so they set the pane and navigate nothing. The rest are whole-screen
 * destinations: they route, and the column collapses away.
 */
export function NavRail() {
  const view = useAppView();
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG, import.meta.env.DEV);

  const { counts: inboxCounts } = useInboxAllReports({
    ignoreFilters: true,
    refetchIntervalMs: INBOX_REFETCH_INTERVAL_MS,
  });
  const { unreadCount: unseenActivity } = useTaskActivity();
  const commandCenterCount = useCommandCenterActiveCount();
  const counts: RailCounts = {
    inbox: inboxCounts.pulls,
    activity: unseenActivity,
    commandCenter: commandCenterCount,
  };
  const railPane = useNavRailStore((s) => s.pane);
  const setRailPane = useNavRailStore((s) => s.setPane);
  const inWebsiteTree = useRouterState({
    select: (s) => s.location.pathname.startsWith("/website"),
  });
  // Hiding and reordering nav items is a sidebar setting; the rail is one of
  // the two shells that honors it.
  const navItemOverrides = useSidebarStore((s) => s.navItemOverrides);
  const navItemOrder = useSidebarStore((s) => s.navItemOrder);
  const destinations = visibleRailDestinations({
    overrides: navItemOverrides,
    order: navItemOrder,
    loops: loopsEnabled,
  });
  const settingsVisible = isNavItemVisible(navItemOverrides, "configure");

  // Selecting the destination is the whole interaction; what it does beyond
  // that is the destination's own business.
  const pick =
    ({ pane, analyticsId, onPick }: RailDestination) =>
    () => {
      track(ANALYTICS_EVENTS.SIDEBAR_NAV_ITEM_CLICKED, {
        item: analyticsId,
        in_more: false,
        layout: "channels",
      });
      setRailPane(pane);
      onPick?.({ inWebsiteTree });
    };

  // Follow the route, but only when the route itself changes: Spaces and
  // Activity deliberately leave the URL alone, and re-deriving on every render
  // would snap the pane straight back to whatever screen is behind them.
  const routePane = paneForView(view.type);
  useEffect(() => {
    setRailPane(routePane);
  }, [routePane, setRailPane]);

  return (
    // One provider for the rail: once any tooltip is up, moving to its
    // neighbour reveals that one immediately instead of serving the warm-up
    // delay again. Per-tooltip providers (the old primitive mounted its own)
    // cannot do that — the skip window is provider state, and isolated
    // providers never share it.
    <TooltipProvider delay={400}>
      <div
        className="flex h-full shrink-0 flex-col items-center gap-1.5 bg-chrome py-2"
        style={{ width: NAV_RAIL_WIDTH }}
      >
        {destinations.map((destination) => {
          const { pane, label, Icon, count, countTone } = destination;
          const isActive = railPane === pane;
          const badge = (
            <CountBadge
              count={count?.(counts) ?? 0}
              tone={countTone}
              className={ICON_BADGE_CLASS}
            />
          );
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
              icon={<Icon size={16} weight={isActive ? "fill" : "regular"} />}
              label={label}
              shortcut={destination.shortcut}
              isActive={isActive}
              onClick={onClick}
              badge={badge}
            />
          );
        })}
        {/* The foot of the rail: what you reach for, rather than where you
            are. Neither owns a pane, so neither is ever lit. */}
        <div className="mt-auto flex flex-col items-center gap-1.5">
          {settingsVisible && (
            <NavIcon
              icon={<GearSix size={16} />}
              label="Settings"
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
          )}
          <div className="my-0.5 w-5 shrink-0 border-border border-t" />
          <ProjectSwitcher appearance="icon" />
        </div>
      </div>
    </TooltipProvider>
  );
}
