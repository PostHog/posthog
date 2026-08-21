import {
  BellIcon,
  EnvelopeSimple,
  GearSix,
  HouseSimple,
  Lightning,
} from "@phosphor-icons/react";
import {
  Button,
  Kbd,
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
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import {
  showChannelsRailPane,
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
  navigateToHome,
  navigateToInbox,
  navigateToLoops,
  navigateToWebsiteCommandCenter,
} from "@posthog/ui/router/navigationBridge";
import { useAppView } from "@posthog/ui/router/useAppView";
import { track } from "@posthog/ui/shell/analytics";
import type { ReactNode } from "react";

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

/**
 * The app's leftmost column: the project menu on top, then every destination as
 * an icon.
 *
 * It sits outside the resizable sidebar, so collapsing that sidebar leaves the
 * destinations reachable. Two of them own the column to the rail's right —
 * Home shows the channel tree, Activity shows the activity feed — and picking
 * one is view state, not a route, which is why they set the pane rather than
 * navigate. The rest have no sidebar list of their own, so they route the main
 * pane and leave the column showing whatever it was showing.
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

  const withTrack = (item: SidebarNavItem, action: () => void) => () => {
    track(ANALYTICS_EVENTS.SIDEBAR_NAV_ITEM_CLICKED, {
      item,
      in_more: false,
      layout: "channels",
    });
    action();
  };

  // A deep link to the Activity page lights the same entry, so the rail agrees
  // with the screen even when the route, not the rail, put you there.
  const isActivity = railPane === "activity" || view.type === "activity";
  const isInbox = view.type === "inbox";
  const isCommandCenter = view.type === "command-center";
  const isLoops = view.type === "loops";
  // Home stays lit while you read a channel or a task: those are all reached
  // through its tree, so the rail keeps pointing at where you came in.
  const isHome = !isActivity && !isInbox && !isCommandCenter && !isLoops;

  const goHome = () => {
    showChannelsRailPane();
    navigateToHome();
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
          icon={<HouseSimple size={16} weight={isHome ? "fill" : "regular"} />}
          label="Home"
          isActive={isHome}
          onClick={withTrack("home", goHome)}
        />
        <NavIcon
          icon={
            <EnvelopeSimple size={16} weight={isInbox ? "fill" : "regular"} />
          }
          label="Inbox"
          shortcut={formatHotkey(SHORTCUTS.INBOX)}
          isActive={isInbox}
          onClick={withTrack("inbox", navigateToInbox)}
          badge={
            <CountBadge count={counts.pulls} className={ICON_BADGE_CLASS} />
          }
        />
        <NavIcon
          icon={<BellIcon size={16} weight={isActivity ? "fill" : "regular"} />}
          label="Activity"
          isActive={isActivity}
          onClick={withTrack("activity", () => setRailPane("activity"))}
          badge={
            <CountBadge count={unseenActivity} className={ICON_BADGE_CLASS} />
          }
        />
        <NavIcon
          icon={
            <Lightning
              size={16}
              weight={isCommandCenter ? "fill" : "regular"}
            />
          }
          label="Command Center"
          isActive={isCommandCenter}
          onClick={withTrack("command_center", navigateToWebsiteCommandCenter)}
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
            icon={<LoopIcon size={16} weight={isLoops ? "fill" : "regular"} />}
            label="Loops"
            isActive={isLoops}
            onClick={withTrack("loops", navigateToLoops)}
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
