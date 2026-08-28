import { BellIcon, GearSix, MagnifyingGlass } from "@phosphor-icons/react";
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
import { useOpenBrowserTab } from "@posthog/ui/features/browser-tabs/useOpenBrowserTab";
import { useSpacesTabs } from "@posthog/ui/features/browser-tabs/useSpacesTabs";
import { ActivityHoverCard } from "@posthog/ui/features/canvas/components/ActivityHoverCard";
import {
  pickRailDestination,
  type RailCounts,
  type RailDestination,
  visibleRailDestinations,
} from "@posthog/ui/features/canvas/components/railDestinations";
import { useRailPane } from "@posthog/ui/features/canvas/hooks/useRailSurface";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useActivityFilterStore } from "@posthog/ui/features/canvas/stores/activityFilterStore";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { useCommandCenterActiveCount } from "@posthog/ui/features/command-center/useCommandCenterActiveCount";
import { useChannelReportsEnabled } from "@posthog/ui/features/feature-flags/useChannelReportsEnabled";
import { useContextLayerFlag } from "@posthog/ui/features/feature-flags/useContextLayerFlag";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useReportsInboxEnabled } from "@posthog/ui/features/feature-flags/useReportsInboxEnabled";
import { useInboxDecisionCount } from "@posthog/ui/features/inbox/hooks/useInboxDecisionCount";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { ProjectSwitcher } from "@posthog/ui/features/sidebar/components/ProjectSwitcher";
import { NAV_RAIL_WIDTH } from "@posthog/ui/features/sidebar/constants";
import { CountBadge } from "@posthog/ui/primitives/CountBadge";
import { track } from "@posthog/ui/shell/analytics";
import { useCommandMenuStore } from "@posthog/ui/shell/commandMenuStore";
import {
  type ComponentPropsWithRef,
  type MouseEventHandler,
  type ReactElement,
  type ReactNode,
  useState,
} from "react";

const ICON_BADGE_CLASS =
  "-top-1 -right-1 absolute h-3.5 min-w-3.5 w-auto px-1 font-semibold text-[9px] ring-2 ring-chrome";
const NOTIFICATION_DOT_CLASS =
  "top-0 right-0 absolute ring-2 ring-chrome size-2 bg-primary rounded-full";

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
  onClick: MouseEventHandler<HTMLButtonElement>;
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
            className="group relative shrink-0 pl-0 text-muted-foreground data-selected:bg-fill-selected data-selected:text-foreground"
          >
            {icon}
            {badge}
          </Button>
        }
      />
      <TooltipContent side="right">
        {label}
        {shortcut && <Kbd>{shortcut}</Kbd>}
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
  onClick: MouseEventHandler<HTMLButtonElement>;
}) {
  const bell = (
    <NavButton
      icon={<BellIcon size={16} weight={isActive ? "fill" : "regular"} />}
      label="Activity"
      isActive={isActive}
      onClick={onClick}
      badge={badge}
      className="pl-0"
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
  const loopsEnabled = useFeatureFlag(LOOPS_FLAG);
  const contextEnabled = useContextLayerFlag();
  const channelReportsEnabled = useChannelReportsEnabled();
  const reportsInboxEnabled = useReportsInboxEnabled();
  const tabsEnabled = useSpacesTabs();
  const openBrowserTab = useOpenBrowserTab();
  const mentionsEnabled = useActivityFilterStore(
    (state) => state.mentionsEnabled,
  );

  const inboxAvailable = !channelReportsEnabled || reportsInboxEnabled;
  const destinations = visibleRailDestinations({
    home: homeEnabled,
    inbox: inboxAvailable,
    loops: loopsEnabled,
    context: contextEnabled,
  });
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

  const pick =
    (destination: RailDestination): MouseEventHandler<HTMLButtonElement> =>
    (event) => {
      track(ANALYTICS_EVENTS.SIDEBAR_NAV_ITEM_CLICKED, {
        item: destination.analyticsId,
        in_more: false,
        layout: "channels",
      });
      if (tabsEnabled && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        openBrowserTab(destination.href);
        return;
      }
      pickRailDestination(destination, railPane);
    };

  return (
    // One provider for the whole rail: the tooltip skip window is provider
    // state, so isolated providers never share it.
    <TooltipProvider delay={400}>
      <div
        data-testid="nav-rail"
        className="relative z-[60] flex h-full shrink-0 flex-col items-center gap-1.5 bg-chrome py-2"
        style={{ width: NAV_RAIL_WIDTH }}
      >
        {destinations.map((destination) => {
          const { pane, label, Icon, count, countTone } = destination;
          const isActive = railPane === pane;
          const destinationCount = count?.(counts) ?? 0;
          const usesNotificationDot = pane === "activity" || pane === "inbox";
          let badge: ReactNode;
          if (usesNotificationDot) {
            badge =
              destinationCount > 0 ? (
                <span
                  data-slot="dot"
                  className={NOTIFICATION_DOT_CLASS}
                  aria-hidden
                />
              ) : null;
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
                  className={pane === "spaces" ? "size-5" : undefined}
                  size={pane === "spaces" ? 20 : 16}
                  weight={isActive ? "fill" : "regular"}
                />
              }
              label={label}
              shortcut={destination.shortcut}
              isActive={isActive}
              onClick={onClick}
              badge={badge}
            />
          );
        })}
        <div className="mt-auto flex flex-col items-center gap-1.5">
          <NavIcon
            icon={<MagnifyingGlass size={16} />}
            label="Search"
            shortcut={formatHotkey(SHORTCUTS.COMMAND_MENU)}
            isActive={false}
            onClick={toggleCommandMenu}
          />
          <NavIcon
            icon={<GearSix size={16} />}
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
          <div className="my-0.5 w-5 shrink-0 border-border border-t" />
          <ProjectSwitcher appearance="icon" />
        </div>
      </div>
    </TooltipProvider>
  );
}
