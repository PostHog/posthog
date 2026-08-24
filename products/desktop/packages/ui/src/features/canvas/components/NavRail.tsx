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
import { DESKTOP_HOME_FLAG, LOOPS_FLAG } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { ActivityHoverCard } from "@posthog/ui/features/canvas/components/ActivityHoverCard";
import {
  pickRailDestination,
  type RailCounts,
  type RailDestination,
  visibleRailDestinations,
} from "@posthog/ui/features/canvas/components/railDestinations";
import { useRailPane } from "@posthog/ui/features/canvas/hooks/useRailSurface";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useCommandCenterActiveCount } from "@posthog/ui/features/command-center/useCommandCenterActiveCount";
import { useContextLayerFlag } from "@posthog/ui/features/feature-flags/useContextLayerFlag";
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
import { track } from "@posthog/ui/shell/analytics";
import {
  type ComponentPropsWithRef,
  type ReactElement,
  type ReactNode,
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

// No peek once Activity is the destination: the feed is already beside you.
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
 * The app's leftmost column. Sits outside the resizable sidebar, so collapsing
 * that sidebar leaves the destinations reachable.
 */
export function NavRail() {
  const homeEnabled = useFeatureFlag(DESKTOP_HOME_FLAG);
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG, import.meta.env.DEV);
  const contextEnabled = useContextLayerFlag();

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
  // The route is the only thing that says where you are, so the rail cannot
  // light a destination the screen isn't on.
  const railPane = useRailPane();
  const navItemOverrides = useSidebarStore((s) => s.navItemOverrides);
  const navItemOrder = useSidebarStore((s) => s.navItemOrder);
  const destinations = visibleRailDestinations({
    overrides: navItemOverrides,
    order: navItemOrder,
    home: homeEnabled,
    loops: loopsEnabled,
    context: contextEnabled,
  });
  const settingsVisible = isNavItemVisible(navItemOverrides, "configure");

  const pick = (destination: RailDestination) => () => {
    track(ANALYTICS_EVENTS.SIDEBAR_NAV_ITEM_CLICKED, {
      item: destination.analyticsId,
      in_more: false,
      layout: "channels",
    });
    pickRailDestination(destination, railPane);
  };

  return (
    // One provider for the whole rail: the tooltip skip window is provider
    // state, so isolated providers never share it.
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
