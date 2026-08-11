import {
  BellIcon,
  EnvelopeSimpleIcon,
  GearSixIcon,
  HouseIcon,
  LightningIcon,
  MagnifyingGlassIcon,
  PencilSimpleIcon,
  PlusIcon,
  StarIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
  Input,
  MenuLabel,
} from "@posthog/quill";
import {
  ANALYTICS_EVENTS,
  type SidebarNavItem,
} from "@posthog/shared/analytics-events";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import { RenameChannelModal } from "@posthog/ui/features/canvas/components/RenameChannelModal";
import { useBlockedSessionCount } from "@posthog/ui/features/canvas/hooks/useBlockedSessionCount";
import { useChannelStarToggle } from "@posthog/ui/features/canvas/hooks/useChannelStars";
import {
  type Channel,
  useChannelMutations,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useUnreadSessionCount } from "@posthog/ui/features/canvas/hooks/useUnreadSessionCount";
import { useSpaceTreeStore } from "@posthog/ui/features/canvas/stores/spaceTreeStore";
import { useCommandCenterActiveCount } from "@posthog/ui/features/command-center/useCommandCenterActiveCount";
import { useInboxAllReports } from "@posthog/ui/features/inbox/hooks/useInboxAllReports";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { DOT_TONE_VAR } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import {
  navigateToInbox,
  navigateToWebsiteCommandCenter,
} from "@posthog/ui/router/navigationBridge";
import { useAppView } from "@posthog/ui/router/useAppView";
import { track } from "@posthog/ui/shell/analytics";
import { useRouterState } from "@tanstack/react-router";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  navigateToSpaceFresh,
  patchNavPanelSearch,
  useNavPanelSearch,
  useSecondaryPanelState,
} from "../useNavPanels";

const INBOX_REFETCH_INTERVAL_MS = 60_000;

const trackNav = (item: SidebarNavItem) =>
  track(ANALYTICS_EVENTS.SIDEBAR_NAV_ITEM_CLICKED, {
    item,
    in_more: false,
    layout: "channels",
  });

/** One dot however many items — the row's job is "there is something in here". */
function AttentionDot({
  count,
  tone,
}: {
  count: number;
  tone: "attention" | "blocked";
}) {
  if (count === 0) return null;
  return (
    <span
      aria-label={`${count} ${tone === "blocked" ? "waiting on you" : "unread"}`}
      role="img"
      className="h-1.5 w-1.5 shrink-0 rounded-full"
      style={{
        backgroundColor:
          tone === "blocked" ? DOT_TONE_VAR.blue : "var(--primary)",
      }}
    />
  );
}

function SpaceRow({
  channel,
  isActive,
  onClick,
  onRename,
  onDelete,
}: {
  channel: Channel;
  isActive: boolean;
  onClick: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  const { isStarred, toggleStar } = useChannelStarToggle(channel);
  const unreadCount = useUnreadSessionCount()(channel.id);
  const blockedCount = useBlockedSessionCount()(channel.id);
  const isPersonal = channel.channelType === "personal";

  const row = (
    <SidebarItem
      depth={1}
      label={channel.name}
      isActive={isActive}
      onClick={onClick}
      badge={
        blockedCount > 0 ? (
          <AttentionDot count={blockedCount} tone="blocked" />
        ) : (
          <AttentionDot count={unreadCount} tone="attention" />
        )
      }
    />
  );

  // #me is yours alone — nothing on it to star, rename, or delete.
  if (isPersonal) return row;

  return (
    <ContextMenu>
      <ContextMenuTrigger render={<div>{row}</div>} />
      <ContextMenuContent className="w-auto min-w-fit">
        <ContextMenuItem onClick={toggleStar}>
          <StarIcon size={14} weight={isStarred ? "fill" : "regular"} />
          {isStarred ? "Unstar space" : "Star space"}
        </ContextMenuItem>
        <ContextMenuItem onClick={onRename}>
          <PencilSimpleIcon size={14} />
          Rename space…
        </ContextMenuItem>
        <ContextMenuItem variant="destructive" onClick={onDelete}>
          <TrashIcon size={14} />
          Delete space…
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

/**
 * The new chrome's primary sidebar body: top-level destinations, then the
 * starred and remaining spaces as plain rows (sessions live in the secondary
 * panel now), with Settings pinned to the bottom. Rendered inside
 * ChannelsSidebar's ResizableSidebar, below the project switcher.
 */
export function PrimarySidebar() {
  const view = useAppView();
  const search = useNavPanelSearch();
  const { destination, open: panelOpen } = useSecondaryPanelState();
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  const { channels } = useChannels();
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [renaming, setRenaming] = useState<Channel | null>(null);
  const [deleting, setDeleting] = useState<Channel | null>(null);
  const { deleteChannel, isDeleting } = useChannelMutations();

  const { counts: inboxCounts } = useInboxAllReports({
    ignoreFilters: true,
    refetchIntervalMs: INBOX_REFETCH_INTERVAL_MS,
  });
  const { unreadCount: unseenActivity } = useTaskActivity();
  const commandCenterCount = useCommandCenterActiveCount();

  // ⌘⇧S (ChannelHotkeys) asks for the space search from anywhere — it used to
  // slide the old sidebar back to its list; here it opens and focuses the
  // sidebar's search box.
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const searchFocusRequest = useSpaceTreeStore((s) => s.searchFocusRequest);
  useEffect(() => {
    if (searchFocusRequest === 0) return;
    setSearchOpen(true);
    searchInputRef.current?.focus();
  }, [searchFocusRequest]);

  const normalizedQuery = query.trim().toLowerCase();
  const visible = useMemo(
    () =>
      normalizedQuery
        ? channels.filter((c) => c.name.toLowerCase().includes(normalizedQuery))
        : channels,
    [channels, normalizedQuery],
  );
  // #me leads Starred; the rest keep the list's alphabetical order.
  const starred = useMemo(
    () => [
      ...visible.filter((c) => c.channelType === "personal"),
      ...visible.filter((c) => c.channelType !== "personal" && c.starred),
    ],
    [visible],
  );
  const unstarred = useMemo(
    () => visible.filter((c) => c.channelType !== "personal" && !c.starred),
    [visible],
  );

  const activeSpaceId =
    destination?.kind === "space" ? destination.channelId : null;
  const isActivity = search.panel === "activity";
  const isHome = pathname === "/website" && !isActivity;

  const onSpaceClick = (channel: Channel) => {
    if (activeSpaceId === channel.id && !isActivity) {
      // Re-clicking the current space toggles its panel.
      patchNavPanelSearch({ panel: panelOpen ? "off" : null });
      return;
    }
    navigateToSpaceFresh(channel.id);
  };

  const onActivityClick = () => {
    trackNav("activity");
    patchNavPanelSearch({ panel: isActivity ? "off" : "activity" });
  };

  const spaceRow = (channel: Channel): ReactNode => (
    <SpaceRow
      key={channel.id}
      channel={channel}
      isActive={activeSpaceId === channel.id && !isActivity}
      onClick={() => onSpaceClick(channel)}
      onRename={() => setRenaming(channel)}
      onDelete={() => setDeleting(channel)}
    />
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-col gap-px px-2 pt-1">
        <SidebarItem
          depth={0}
          icon={<HouseIcon size={16} weight={isHome ? "fill" : "regular"} />}
          label="Home"
          isActive={isHome}
          onClick={() => navigateToSpaceFresh(null)}
        />
        <SidebarItem
          depth={0}
          icon={<BellIcon size={16} weight={isActivity ? "fill" : "regular"} />}
          label="Activity"
          isActive={isActivity}
          onClick={onActivityClick}
          badge={<AttentionDot count={unseenActivity} tone="attention" />}
        />
        <SidebarItem
          depth={0}
          icon={
            <EnvelopeSimpleIcon
              size={16}
              weight={view.type === "inbox" ? "fill" : "regular"}
            />
          }
          label="Inbox"
          isActive={view.type === "inbox"}
          onClick={() => {
            trackNav("inbox");
            navigateToInbox();
          }}
          badge={<AttentionDot count={inboxCounts.pulls} tone="attention" />}
        />
        <SidebarItem
          depth={0}
          icon={
            <LightningIcon
              size={16}
              weight={view.type === "command-center" ? "fill" : "regular"}
            />
          }
          label="Command Center"
          isActive={view.type === "command-center"}
          onClick={() => {
            trackNav("command_center");
            navigateToWebsiteCommandCenter();
          }}
          badge={<AttentionDot count={commandCenterCount} tone="attention" />}
        />
      </div>

      <div className="scroll-mask-4 mt-2 min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {starred.length > 0 && (
          <>
            <MenuLabel>Starred</MenuLabel>
            <div className="flex flex-col gap-px">{starred.map(spaceRow)}</div>
          </>
        )}
        <div className="flex items-center gap-0.5">
          <div className="min-w-0 flex-1">
            <MenuLabel>Spaces</MenuLabel>
          </div>
          <Button
            variant="default"
            size="icon-xs"
            aria-label="Search spaces"
            aria-pressed={searchOpen}
            onClick={() => {
              if (searchOpen) setQuery("");
              setSearchOpen(!searchOpen);
            }}
            className="text-muted-foreground"
          >
            <MagnifyingGlassIcon size={12} />
          </Button>
          <Button
            variant="default"
            size="icon-xs"
            aria-label="New space"
            onClick={() => setCreateOpen(true)}
            className="text-muted-foreground"
          >
            <PlusIcon size={12} />
          </Button>
        </div>
        {searchOpen && (
          <div className="px-1 pb-1">
            <Input
              autoFocus
              ref={searchInputRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search spaces…"
              aria-label="Search spaces"
              className="h-6 text-[12px]"
            />
          </div>
        )}
        <div className="flex flex-col gap-px">{unstarred.map(spaceRow)}</div>
      </div>

      <div className="shrink-0 border-border border-t px-2 py-1">
        <SidebarItem
          depth={0}
          icon={<GearSixIcon size={16} />}
          label="Settings"
          isActive={false}
          onClick={() => {
            trackNav("configure");
            openSettings("agents");
          }}
        />
      </div>

      <CreateChannelModal open={createOpen} onOpenChange={setCreateOpen} />
      {renaming && (
        <RenameChannelModal
          channel={renaming}
          open
          onOpenChange={(open) => {
            if (!open) setRenaming(null);
          }}
        />
      )}
      <AlertDialog
        open={deleting != null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
      >
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>Delete space</AlertDialogTitle>
            <AlertDialogDescription>
              Delete <span className="font-medium">{deleting?.name}</span>? Its
              sessions stay, but the space goes for everyone in the project.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              render={
                <Button variant="outline" size="sm">
                  Cancel
                </Button>
              }
            />
            <Button
              variant="destructive"
              size="sm"
              loading={isDeleting}
              disabled={isDeleting || !deleting}
              onClick={() => {
                if (!deleting) return;
                void deleteChannel(deleting.id).finally(() =>
                  setDeleting(null),
                );
              }}
            >
              Delete
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
