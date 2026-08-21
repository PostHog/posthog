import {
  BellIcon,
  EnvelopeSimple,
  GearSix,
  HouseSimple,
  Lightning,
  SquaresFourIcon,
} from "@phosphor-icons/react";
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
import {
  ANALYTICS_EVENTS,
  type SidebarNavItem,
} from "@posthog/shared/analytics-events";
import { ActivityHoverCard } from "@posthog/ui/features/canvas/components/ActivityHoverCard";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { showChannelList } from "@posthog/ui/features/canvas/stores/channelPaneStore";
import {
  type NavRailPane,
  useNavRailStore,
} from "@posthog/ui/features/canvas/stores/navRailStore";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { useCommandCenterActiveCount } from "@posthog/ui/features/command-center/useCommandCenterActiveCount";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { ProjectSwitcher } from "@posthog/ui/features/sidebar/components/ProjectSwitcher";
import { NAV_RAIL_WIDTH } from "@posthog/ui/features/sidebar/constants";
import { CountBadge } from "@posthog/ui/primitives/CountBadge";
import { LoopIcon } from "@posthog/ui/primitives/LoopIcon";
import {
  navigateToActivity,
  navigateToHome,
  navigateToInbox,
  navigateToLoops,
  navigateToWebsiteCommandCenter,
} from "@posthog/ui/router/navigationBridge";
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
  unreadCount,
  onClick,
}: {
  isActive: boolean;
  unreadCount: number;
  onClick: () => void;
}) {
  const bell = (
    <NavButton
      icon={<BellIcon size={16} weight={isActive ? "fill" : "regular"} />}
      label="Activity"
      isActive={isActive}
      onClick={onClick}
      badge={<CountBadge count={unreadCount} className={ICON_BADGE_CLASS} />}
    />
  );

  if (isActive) return bell;
  return <ActivityHoverPopover trigger={bell} />;
}

/**
 * Which destination a route belongs to, so a deep link, a back button or a
 * ⌘1-9 jump lights the same entry the rail would have. Anything reached through
 * the space tree — a channel, a task, a new-task screen — belongs to Spaces.
 */
function paneForView(viewType: string): NavRailPane {
  switch (viewType) {
    case "home":
      return "home";
    case "inbox":
      return "inbox";
    case "command-center":
      return "command-center";
    case "loops":
      return "loops";
    case "activity":
      return "activity";
    default:
      return "spaces";
  }
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

  const { counts } = useInboxAllReports({
    ignoreFilters: true,
    refetchIntervalMs: INBOX_REFETCH_INTERVAL_MS,
  });
  const { unreadCount: unseenActivity } = useTaskActivity();
  const commandCenterCount = useCommandCenterActiveCount();
  const railPane = useNavRailStore((s) => s.pane);
  const setRailPane = useNavRailStore((s) => s.setPane);
  const inWebsiteTree = useRouterState({
    select: (s) => s.location.pathname.startsWith("/website"),
  });

  const withTrack = (item: SidebarNavItem, action: () => void) => () => {
    track(ANALYTICS_EVENTS.SIDEBAR_NAV_ITEM_CLICKED, {
      item,
      in_more: false,
      layout: "channels",
    });
    action();
  };

  // Follow the route, but only when the route itself changes: Spaces and
  // Activity deliberately leave the URL alone, and re-deriving on every render
  // would snap the pane straight back to whatever screen is behind them.
  const routePane = paneForView(view.type);
  useEffect(() => {
    setRailPane(routePane);
  }, [routePane, setRailPane]);

  const go = (pane: NavRailPane, navigate?: () => void) => () => {
    setRailPane(pane);
    navigate?.();
  };

  // Spaces and Activity draw into the content pane the /website layout owns, so
  // they only work from inside that tree. Inbox and Loops still live in /code —
  // picked from there, Activity would set its pane and then have nowhere to
  // draw, leaving the reader looking at the inbox with a dead feed beside it.
  // From inside /website it still navigates nothing, which is what lets Spaces
  // put you back on the screen Activity was covering.
  const goActivity = () => {
    setRailPane("activity");
    if (!inWebsiteTree) navigateToActivity();
  };

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
        <NavIcon
          icon={
            <HouseSimple
              size={16}
              weight={railPane === "home" ? "fill" : "regular"}
            />
          }
          label="Home"
          isActive={railPane === "home"}
          onClick={withTrack("home", go("home", navigateToHome))}
        />
        <NavIcon
          icon={
            <SquaresFourIcon
              size={16}
              weight={railPane === "spaces" ? "fill" : "regular"}
            />
          }
          label="Spaces"
          isActive={railPane === "spaces"}
          // Always the list, even from inside a space: this is the entry to the
          // tree, and the space you were in stays scoped behind it — the route
          // and the pane beside it don't move, so nothing is lost by looking.
          onClick={withTrack("spaces", go("spaces", showChannelList))}
        />
        <ActivityNavItem
          isActive={railPane === "activity"}
          unreadCount={unseenActivity}
          onClick={withTrack("activity", goActivity)}
        />
        <NavIcon
          icon={
            <EnvelopeSimple
              size={16}
              weight={railPane === "inbox" ? "fill" : "regular"}
            />
          }
          label="Inbox"
          shortcut={formatHotkey(SHORTCUTS.INBOX)}
          isActive={railPane === "inbox"}
          onClick={withTrack("inbox", go("inbox", navigateToInbox))}
          badge={
            <CountBadge count={counts.pulls} className={ICON_BADGE_CLASS} />
          }
        />
        <NavIcon
          icon={
            <Lightning
              size={16}
              weight={railPane === "command-center" ? "fill" : "regular"}
            />
          }
          label="Command Center"
          isActive={railPane === "command-center"}
          onClick={withTrack(
            "command_center",
            go("command-center", navigateToWebsiteCommandCenter),
          )}
          badge={
            <CountBadge
              count={commandCenterCount}
              tone="neutral"
              className={ICON_BADGE_CLASS}
            />
          }
        />
        {loopsEnabled ? (
          <NavIcon
            icon={
              <LoopIcon
                size={16}
                weight={railPane === "loops" ? "fill" : "regular"}
              />
            }
            label="Loops"
            isActive={railPane === "loops"}
            onClick={withTrack("loops", go("loops", navigateToLoops))}
          />
        ) : null}
        <div className="mt-auto" />
        <NavIcon
          icon={<GearSix size={16} />}
          label="Settings"
          isActive={false}
          onClick={withTrack("configure", () => openSettings())}
        />
        <div className="my-0.5 w-5 shrink-0 border-border border-t" />
        <ProjectSwitcher appearance="icon" />
      </div>
    </TooltipProvider>
  );
}
