import { Collapsible } from "@base-ui/react/collapsible";
import {
  CaretDownIcon,
  CaretRightIcon,
  ChartBarIcon,
  DotsThreeIcon,
  FileTextIcon,
  HashIcon,
  LinkIcon,
  LockSimpleIcon,
  PencilSimpleIcon,
  PlusIcon,
  StarIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import {
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  ButtonGroup,
  AlertDialog as ConfirmDialog,
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Empty,
  EmptyHeader,
  MenuLabel,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { RenameChannelModal } from "@posthog/ui/features/canvas/components/RenameChannelModal";
import { trackAndCreateCanvas } from "@posthog/ui/features/canvas/createCanvasAnalytics";
import { ensurePersonalChannel } from "@posthog/ui/features/canvas/ensurePersonalChannel";
import {
  useChannelStars,
  useChannelStarToggle,
} from "@posthog/ui/features/canvas/hooks/useChannelStars";
import {
  type Channel,
  useChannelMutations,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { useCreateAndOpenDashboard } from "@posthog/ui/features/canvas/hooks/useDashboards";
import {
  PERSONAL_CHANNEL_NAME,
  useTaskChannels,
} from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useIsChannelUnread } from "@posthog/ui/features/canvas/hooks/useUnreadChannels";
import { copyChannelLink } from "@posthog/ui/features/canvas/utils/copyChannelLink";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { Box, Flex } from "@radix-ui/themes";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { Fragment, type ReactNode, useEffect, useRef, useState } from "react";
import { hostClient } from "../hostClient";

// One actionable entry in a channel's menu, rendered the same whether it
// surfaces in the hover "..." dropdown or the right-click context menu.
type ChannelActionItem = {
  key: string;
  label: string;
  icon: ReactNode;
  onSelect: () => void;
  variant?: "destructive";
  disabled?: boolean;
  // Draw a divider above this item to separate it from the previous group.
  separatorBefore?: boolean;
};

// The channel actions (star, copy link, rename, delete) plus the rename-modal
// state they drive. Single source of truth so the dropdown and context menus
// stay in lockstep — add an action here and both surfaces pick it up.
function useChannelActions(channel: Channel): {
  actions: ChannelActionItem[];
  renameOpen: boolean;
  setRenameOpen: (open: boolean) => void;
  confirmDeleteOpen: boolean;
  setConfirmDeleteOpen: (open: boolean) => void;
  confirmDelete: () => Promise<boolean>;
  isDeleting: boolean;
} {
  const [renameOpen, setRenameOpen] = useState(false);
  // "Delete channel" opens a confirmation dialog rather than deleting inline —
  // the action is destructive and irreversible.
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { deleteChannel, isDeleting } = useChannelMutations();
  const { isStarred, toggleStar, removeStar } = useChannelStarToggle(channel);

  // Runs the actual delete once confirmed. Returns whether it succeeded so the
  // dialog can stay open (and show the toast) on failure.
  const confirmDelete = async (): Promise<boolean> => {
    try {
      // Unfile the channel's dashboards + filed tasks first. The folder delete
      // would also cascade, but doing it explicitly via the typed endpoints
      // surfaces failures clearly. Best-effort — a failed child shouldn't
      // block removing the channel.
      const [dashboards, channelTasks] = await Promise.all([
        hostClient().dashboards.list.query({ channelId: channel.id }),
        hostClient().channelTasks.list.query({ channelId: channel.id }),
      ]);
      await Promise.allSettled([
        ...dashboards.map((d) =>
          hostClient().dashboards.delete.mutate({ id: d.id }),
        ),
        ...channelTasks.map((t) =>
          hostClient().channelTasks.unfile.mutate({ id: t.id }),
        ),
      ]);

      await deleteChannel(channel.id);
      removeStar();
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "delete",
        surface: "sidebar",
        channel_id: channel.id,
        success: true,
      });
      // If we're inside the channel being deleted, fall back to the index.
      if (pathname.startsWith(`/website/${channel.id}`)) {
        void navigate({ to: "/website" });
      }
      return true;
    } catch (error) {
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "delete",
        surface: "sidebar",
        channel_id: channel.id,
        success: false,
      });
      toast.error("Couldn't delete channel", {
        description: error instanceof Error ? error.message : String(error),
      });
      return false;
    }
  };

  const actions: ChannelActionItem[] = [
    {
      key: "star",
      label: isStarred ? "Unstar channel" : "Star channel",
      icon: <StarIcon size={14} weight={isStarred ? "fill" : "regular"} />,
      onSelect: () => {
        track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
          action_type: isStarred ? "unstar" : "star",
          surface: "sidebar",
          channel_id: channel.id,
        });
        toggleStar();
      },
    },
    {
      key: "copy-link",
      label: "Copy link",
      icon: <LinkIcon size={14} />,
      onSelect: () => void copyChannelLink(channel.id, "sidebar"),
    },
    {
      key: "rename",
      label: "Rename channel…",
      icon: <PencilSimpleIcon size={14} />,
      separatorBefore: true,
      onSelect: () => setRenameOpen(true),
    },
    {
      key: "delete",
      label: "Delete channel…",
      icon: <TrashIcon size={14} />,
      variant: "destructive",
      onSelect: () => setConfirmDeleteOpen(true),
    },
  ];

  return {
    actions,
    renameOpen,
    setRenameOpen,
    confirmDeleteOpen,
    setConfirmDeleteOpen,
    confirmDelete,
    isDeleting,
  };
}

// Renders the shared channel actions into either menu primitive. Branching by
// `kind` (rather than a union-typed component) keeps the item/separator props
// type-checked against each primitive.
function ChannelActionItems({
  actions,
  kind,
}: {
  actions: ChannelActionItem[];
  kind: "dropdown" | "context";
}) {
  if (kind === "dropdown") {
    return (
      <>
        {actions.map((a) => (
          <Fragment key={a.key}>
            {a.separatorBefore && <DropdownMenuSeparator />}
            <DropdownMenuItem
              variant={a.variant}
              disabled={a.disabled}
              onClick={a.onSelect}
            >
              {a.icon}
              {a.label}
            </DropdownMenuItem>
          </Fragment>
        ))}
      </>
    );
  }
  return (
    <>
      {actions.map((a) => (
        <Fragment key={a.key}>
          {a.separatorBefore && <ContextMenuSeparator />}
          <ContextMenuItem
            variant={a.variant}
            disabled={a.disabled}
            onClick={a.onSelect}
          >
            {a.icon}
            {a.label}
          </ContextMenuItem>
        </Fragment>
      ))}
    </>
  );
}

// Hover-revealed "..." menu on a channel header. Presentation only — the action
// list comes from `useChannelActions`, so it matches the right-click menu.
function ChannelMenu({
  channelName,
  actions,
  open,
  onOpenChange,
}: {
  channelName: string;
  actions: ChannelActionItem[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <DropdownMenu open={open} onOpenChange={onOpenChange}>
      <DropdownMenuTrigger
        render={
          <Button
            variant="outline"
            size="icon-xs"
            aria-label={`Options for ${channelName}`}
            className={cn(
              "group-hover:border-border",
              "transition-opacity",
              open ? "opacity-100" : "opacity-0 group-hover/chan:opacity-100",
            )}
          >
            <DotsThreeIcon size={14} weight="bold" />
          </Button>
        }
      />
      <DropdownMenuContent
        align="end"
        side="bottom"
        sideOffset={4}
        className="w-auto min-w-fit"
      >
        <ChannelActionItems actions={actions} kind="dropdown" />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

// One channel in the list: a "# name" row that navigates to the channel home.
// No expansion — the channel's surfaces live in the in-channel top nav.
function ChannelSection({
  channel,
  isUnread,
}: {
  channel: Channel;
  /** Bolds the name: activity here the viewer hasn't seen. */
  isUnread?: boolean;
}) {
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const base = `/website/${channel.id}`;
  // Highlight the row whenever any of the channel's routes is open.
  const isActive = pathname === base || pathname.startsWith(`${base}/`);
  // Lifted so the hover button group stays visible while the menu is open.
  const [menuOpen, setMenuOpen] = useState(false);
  // The "+" dropdown (New task / New canvas). Keeps the hover actions pinned
  // while open.
  const [newMenuOpen, setNewMenuOpen] = useState(false);
  const createAndOpenCanvas = useCreateAndOpenDashboard(channel.id);
  // Shared by the "..." dropdown and the right-click context menu so both offer
  // the same star / edit / rename / delete actions.
  const {
    actions,
    renameOpen,
    setRenameOpen,
    confirmDeleteOpen,
    setConfirmDeleteOpen,
    confirmDelete,
    isDeleting,
  } = useChannelActions(channel);

  return (
    <Box className="group/chan relative">
      {/* A single, non-expandable row: the "# name" navigates straight to the
          channel home. Right-clicking opens the same actions as the "..." menu. */}
      <ContextMenu>
        <ContextMenuTrigger
          render={
            <Button
              variant="default"
              size="default"
              left
              data-selected={isActive || undefined}
              onClick={() => {
                track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
                  action_type: "nav_click",
                  surface: "sidebar",
                  channel_id: channel.id,
                });
                void navigate({
                  to: "/website/$channelId",
                  params: { channelId: channel.id },
                });
              }}
              className="w-full min-w-0 justify-start gap-2 data-selected:bg-fill-selected data-selected:text-gray-12"
            >
              <HashIcon
                size={14}
                weight={isUnread ? "bold" : undefined}
                className={cn(
                  "shrink-0",
                  isUnread || isActive
                    ? "text-foreground"
                    : "text-muted-foreground group-hover/button:text-foreground",
                )}
              />
              <span
                className={cn(
                  "truncate text-[13px] group-hover/chan:pr-8",
                  // Bold is unread's alone; full contrast is shared with the
                  // channel you're in. Either way there's no hover brighten
                  // left to do, so those rows skip it.
                  isUnread ? "font-bold" : "font-medium",
                  isUnread || isActive
                    ? "text-foreground"
                    : "text-muted-foreground group-hover/button:text-foreground",
                  menuOpen && "pr-8",
                )}
              >
                {channel.name}
              </span>
            </Button>
          }
        />
        <ContextMenuContent>
          <ChannelActionItems actions={actions} kind="context" />
        </ContextMenuContent>
      </ContextMenu>
      {/* Hover actions: the "+" dropdown (New task / New canvas) and the
            options menu. Stay visible while either is open. */}
      <div className="absolute top-1 right-1">
        <ButtonGroup>
          <DropdownMenu open={newMenuOpen} onOpenChange={setNewMenuOpen}>
            <Tooltip>
              <TooltipTrigger
                render={
                  <DropdownMenuTrigger
                    render={
                      <Button
                        variant="outline"
                        size="icon-xs"
                        aria-label={`New in ${channel.name}`}
                        className={cn(
                          "gap-1 transition-opacity group-hover:border-border",
                          menuOpen || newMenuOpen
                            ? "opacity-100"
                            : "opacity-0 group-hover/chan:opacity-100",
                        )}
                      >
                        <PlusIcon size={12} weight="bold" />
                      </Button>
                    }
                  />
                }
              />
              <TooltipContent side="top">New…</TooltipContent>
            </Tooltip>
            <DropdownMenuContent
              align="start"
              side="bottom"
              sideOffset={4}
              className="w-auto min-w-fit"
            >
              <DropdownMenuItem
                onClick={() => {
                  track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
                    action_type: "new_task_open",
                    surface: "sidebar",
                    channel_id: channel.id,
                  });
                  navigate({
                    to: "/website/$channelId/new",
                    params: { channelId: channel.id },
                  });
                }}
              >
                <FileTextIcon size={14} />
                New task
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => {
                  // Create + open a canvas with the default template directly;
                  // the canvas's own composer drives what gets built.
                  trackAndCreateCanvas(
                    channel.id,
                    undefined,
                    "sidebar",
                    () => void createAndOpenCanvas(),
                  );
                }}
              >
                <ChartBarIcon size={14} />
                New canvas
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <ChannelMenu
            channelName={channel.name}
            actions={actions}
            open={menuOpen}
            onOpenChange={setMenuOpen}
          />
        </ButtonGroup>
      </div>
      {/* One modal for both the dropdown and context-menu "Rename" actions. */}
      <RenameChannelModal
        channel={channel}
        open={renameOpen}
        onOpenChange={setRenameOpen}
      />
      {/* Destructive confirm for "Delete channel" — spells out what's removed. */}
      <ConfirmDialog
        open={confirmDeleteOpen}
        onOpenChange={setConfirmDeleteOpen}
      >
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {channel.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently deletes the channel and can’t be undone.
              <ul className="list-disc ps-4">
                <li>
                  The channel and its{" "}
                  <span className="font-medium">CONTEXT.md</span> are deleted.
                </li>
                <li>
                  Every canvas saved in this channel is permanently deleted.
                </li>
                <li>
                  Filed tasks are removed from the channel, but the tasks
                  themselves are not deleted.
                </li>
              </ul>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              render={<Button variant="outline">Cancel</Button>}
            />
            <Button
              variant="primary"
              loading={isDeleting}
              onClick={() =>
                void confirmDelete().then((ok) => {
                  if (ok) setConfirmDeleteOpen(false);
                })
              }
            >
              Delete channel
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </ConfirmDialog>
    </Box>
  );
}

// The user's private "#me" channel, pinned above the shared channel list.
// The feed and task ownership live on the per-user backend personal channel;
// the "me" folder is the bridge that keeps the folder-keyed surfaces
// (CONTEXT.md, artifacts) routable, created lazily on first open.
function PersonalChannelRow() {
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { channels } = useChannels();
  const { createChannel, isCreating } = useChannelMutations();
  // Listing backend channels lazily provisions the personal channel server-side.
  useTaskChannels();
  // The "+" dropdown (New task / New canvas), mirroring a shared channel row.
  const [newMenuOpen, setNewMenuOpen] = useState(false);
  const isUnread = useIsChannelUnread()(PERSONAL_CHANNEL_NAME);

  const meFolder = channels.find((c) => c.name === PERSONAL_CHANNEL_NAME);
  const createAndOpenCanvas = useCreateAndOpenDashboard(meFolder?.id);
  const isActive =
    !!meFolder &&
    (pathname === `/website/${meFolder.id}` ||
      pathname.startsWith(`/website/${meFolder.id}/`));

  // The "me" folder is created on first use, so every action resolves the id
  // rather than closing over it — the row is actionable before it exists. The
  // create is shared (ensurePersonalChannel) so a row click racing its "+" menu
  // can't provision two.
  const ensureFolderId = async (): Promise<string | undefined> => {
    try {
      return (await ensurePersonalChannel(channels, createChannel)).id;
    } catch (error) {
      toast.error("Couldn't open me", {
        description: error instanceof Error ? error.message : String(error),
      });
      return undefined;
    }
  };

  const open = async () => {
    const channelId = await ensureFolderId();
    if (!channelId) return;
    void navigate({ to: "/website/$channelId", params: { channelId } });
  };

  const newTask = async () => {
    const channelId = await ensureFolderId();
    if (!channelId) return;
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "new_task_open",
      surface: "sidebar",
      channel_id: channelId,
    });
    void navigate({ to: "/website/$channelId/new", params: { channelId } });
  };

  const newCanvas = async () => {
    const channelId = await ensureFolderId();
    if (!channelId) return;
    trackAndCreateCanvas(
      channelId,
      undefined,
      "sidebar",
      () => void createAndOpenCanvas({ channelId }),
    );
  };

  return (
    <Box className="group/chan relative">
      <Button
        variant="default"
        size="default"
        left
        data-selected={isActive || undefined}
        disabled={isCreating}
        onClick={() => void open()}
        className="w-full min-w-0 justify-start gap-2 data-selected:bg-fill-selected data-selected:text-gray-12"
      >
        <HashIcon
          size={14}
          weight={isUnread ? "bold" : undefined}
          className={cn(
            "shrink-0",
            isUnread || isActive
              ? "text-foreground"
              : "text-muted-foreground group-hover/button:text-foreground",
          )}
        />
        <span
          className={cn(
            "truncate text-[13px]",
            isUnread ? "font-bold" : "font-medium",
            isUnread || isActive
              ? "text-foreground"
              : "text-muted-foreground group-hover/button:text-foreground",
          )}
        >
          {PERSONAL_CHANNEL_NAME}
        </span>
        {/* The lock and the hover "+" share the right edge, so fade the lock
            out as the "+" comes in. */}
        <LockSimpleIcon
          size={12}
          className={cn(
            "ml-auto shrink-0 text-chrome-foreground transition-opacity",
            newMenuOpen
              ? "opacity-0"
              : "opacity-100 group-hover/chan:opacity-0",
          )}
        />
      </Button>
      <div className="absolute top-0 right-1">
        <DropdownMenu open={newMenuOpen} onOpenChange={setNewMenuOpen}>
          <Tooltip>
            <TooltipTrigger
              render={
                <DropdownMenuTrigger
                  render={
                    <Button
                      variant="outline"
                      size="icon-xs"
                      aria-label={`New in ${PERSONAL_CHANNEL_NAME}`}
                      className={cn(
                        "gap-1 transition-opacity group-hover:border-border",
                        newMenuOpen
                          ? "opacity-100"
                          : "opacity-0 group-hover/chan:opacity-100",
                      )}
                    >
                      <PlusIcon size={12} weight="bold" />
                    </Button>
                  }
                />
              }
            />
            <TooltipContent side="top">New…</TooltipContent>
          </Tooltip>
          <DropdownMenuContent
            align="start"
            side="bottom"
            sideOffset={4}
            className="w-auto min-w-fit"
          >
            <DropdownMenuItem onClick={() => void newTask()}>
              <FileTextIcon size={14} />
              New task
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => void newCanvas()}>
              <ChartBarIcon size={14} />
              New canvas
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </Box>
  );
}

// Collapse state is keyed per section in the shared sidebar store, so it
// persists across navigation and restarts. Prefixed to stay clear of the Code
// sidebar's folder sections, which key the same set by folder path.
const STARRED_SECTION_ID = "channels:starred";
const CHANNELS_SECTION_ID = "channels:all";

// A collapsible sidebar group ("Starred" / "Channels"). Base UI directly rather
// than quill's Collapsible: quill styles its trigger as a button (which fought
// the label styling) and animates the panel height (which janked on a list this
// long). Unstyled parts give a plain label row that snaps.
//
// The whole header row is the trigger. It rests as a "#" and swaps to a chevron
// on hover or keyboard focus, so the row only advertises the disclosure when
// you're actually reaching for it.
function ChannelGroup({
  sectionId,
  label,
  className,
  children,
}: {
  sectionId: string;
  label: string;
  className?: string;
  children: ReactNode;
}) {
  const collapsedSections = useSidebarStore((s) => s.collapsedSections);
  const toggleSection = useSidebarStore((s) => s.toggleSection);
  const isOpen = !collapsedSections.has(sectionId);

  return (
    <Collapsible.Root
      open={isOpen}
      // The store only exposes a toggle, so drive it from the requested value:
      // an event for the state we're already in is then a no-op rather than an
      // inversion.
      onOpenChange={(open) => {
        if (open !== isOpen) toggleSection(sectionId);
      }}
      className={className}
    >
      {/* MenuLabel carries the sidebar's label styling; `render` keeps it a
          real button so the whole row is clickable. */}
      <Collapsible.Trigger
        className="group/group-trigger flex w-full items-center gap-2"
        render={<MenuLabel render={<button type="button" />} />}
      >
        <span className="relative flex size-3.5 shrink-0 items-center justify-center">
          <HashIcon
            size={14}
            className="group-hover/group-trigger:hidden group-focus-visible/group-trigger:hidden"
          />
          {isOpen ? (
            <CaretDownIcon
              size={14}
              className="hidden group-hover/group-trigger:block group-focus-visible/group-trigger:block"
            />
          ) : (
            <CaretRightIcon
              size={14}
              className="hidden group-hover/group-trigger:block group-focus-visible/group-trigger:block"
            />
          )}
        </span>
        {label}
      </Collapsible.Trigger>
      {/* Stay mounted while collapsed. Every row builds a context menu, a
          dropdown, a tooltip and two dialogs up front, so unmounting on close
          makes each expand rebuild the lot (~940ms for 46 channels, vs ~80ms
          to collapse). */}
      <Collapsible.Panel keepMounted>
        <div className="pl-5">{children}</div>
      </Collapsible.Panel>
    </Collapsible.Root>
  );
}

// The channel list — the Channels space sidebar body. The private "#me"
// channel is pinned at the top; starred channels surface in their own section
// so the ones you use most stay in reach; the rest sit under a "Channels"
// label. Creating anything goes through the floating ChannelsFab, mounted by
// the sidebar outside this scroll region.
export function ChannelsList() {
  const { channels: allChannels, isLoading } = useChannels();
  const { starredRefToShortcutId } = useChannelStars();

  const isUnread = useIsChannelUnread();

  // The "me" folder renders as the pinned personal row, not a shared channel.
  const channels = allChannels.filter((c) => c.name !== PERSONAL_CHANNEL_NAME);
  const starred = channels.filter((c) => starredRefToShortcutId.has(c.path));
  const others = channels.filter((c) => !starredRefToShortcutId.has(c.path));

  // Fire CHANNELS_SPACE_VIEWED once per space mount, after channels first load
  // (so the counts are accurate). The sidebar stays mounted while navigating
  // between channels, so this naturally fires once per entry into the space.
  const viewedTrackedRef = useRef(false);
  useEffect(() => {
    if (isLoading || viewedTrackedRef.current) return;
    viewedTrackedRef.current = true;
    track(ANALYTICS_EVENTS.CHANNELS_SPACE_VIEWED, {
      channel_count: channels.length,
      starred_count: starred.length,
    });
  }, [isLoading, channels.length, starred.length]);

  return (
    // One shared provider groups every row tooltip so that once one shows,
    // moving to the next row reveals its tooltip instantly (no re-delay).
    <TooltipProvider delay={600}>
      {/* Bottom padding clears the floating create button (ChannelsFab), so the
          last channel stays reachable at full scroll. */}
      <Flex direction="column" gap="px" className="px-2 pt-2 pb-16">
        <PersonalChannelRow />

        {starred.length > 0 && (
          <ChannelGroup sectionId={STARRED_SECTION_ID} label="Starred">
            {starred.map((channel) => (
              <ChannelSection
                key={channel.id}
                channel={channel}
                isUnread={isUnread(channel.name)}
              />
            ))}
          </ChannelGroup>
        )}

        <ChannelGroup sectionId={CHANNELS_SECTION_ID} label="Channels">
          {!isLoading && channels.length === 0 && (
            <Empty className="px-2 py-1 text-subtle-foreground text-xs">
              <EmptyHeader className="text-left">No channels yet.</EmptyHeader>
            </Empty>
          )}
          {others.map((channel) => (
            <ChannelSection
              key={channel.id}
              channel={channel}
              isUnread={isUnread(channel.name)}
            />
          ))}
        </ChannelGroup>
      </Flex>
    </TooltipProvider>
  );
}
