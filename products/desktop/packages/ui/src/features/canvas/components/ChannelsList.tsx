import { Collapsible } from "@base-ui/react/collapsible";
import {
  CaretDownIcon,
  CaretRightIcon,
  ChartBarIcon,
  CubeFocusIcon,
  DotsThreeIcon,
  FileTextIcon,
  HashIcon,
  LinkIcon,
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
  Autocomplete,
  AutocompleteClear,
  AutocompleteInput,
  AutocompleteItem,
  AutocompleteList,
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
  Kbd,
  MenuLabel,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
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
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useCreateAndOpenDashboard } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useStarredChannelSlots } from "@posthog/ui/features/canvas/hooks/useStarredChannelSlots";
import {
  PERSONAL_CHANNEL_NAME,
  useTaskChannels,
} from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useIsChannelUnread } from "@posthog/ui/features/canvas/hooks/useUnreadChannels";
import {
  showChannelPane,
  useChannelPaneStore,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import {
  resetCurrentChannel,
  useCurrentChannelStore,
} from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { copyChannelLink } from "@posthog/ui/features/canvas/utils/copyChannelLink";
import { formatHotkey } from "@posthog/ui/features/command/keyboard-shortcuts";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import {
  OverflowTickerText,
  useOverflowTickerReveal,
} from "@posthog/ui/primitives/OverflowTickerText";
import { toast } from "@posthog/ui/primitives/toast";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { Box, Flex } from "@radix-ui/themes";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import {
  type ComponentProps,
  Fragment,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";
import { hostClient } from "../hostClient";

/**
 * A row's clickable surface.
 *
 * Under the layout every row is an Autocomplete option, so ↑/↓/⏎ walk the list
 * whether or not there's a query — the search box is the only thing that ever
 * holds focus, and the list is what it drives. Off the layout there is no
 * search box to drive anything, so the rows stay plain buttons.
 *
 * Both render the same quill Button underneath; the option just routes its
 * clicks and highlight through Autocomplete. Rest props are forwarded because
 * this is handed to `ContextMenuTrigger` as its rendered element.
 */
function SpaceRowSurface({
  asOption,
  optionValue,
  className,
  children,
  ...rest
}: ComponentProps<typeof Button> & {
  asOption: boolean;
  /** Identifies the row to Autocomplete; unused off the layout. */
  optionValue: string;
}) {
  if (!asOption) {
    return (
      <Button
        variant="default"
        size="default"
        left
        className={cn(
          "w-full min-w-0 justify-start gap-2 data-selected:bg-fill-selected data-selected:text-foreground",
          className,
        )}
        {...rest}
      >
        {children}
      </Button>
    );
  }
  return (
    <AutocompleteItem
      value={optionValue}
      className={cn(
        "w-full min-w-0 pr-1 data-selected:bg-fill-selected data-selected:text-foreground",
        // quill wraps an option's children in its own flex row; widening it is
        // what keeps the shortcut hint at the row's right edge and lets the
        // name truncate, exactly as they do in the button above.
        "[&>span]:w-full [&>span]:gap-2",
        // quill highlights an option with an offset focus ring, which suits a
        // popup listbox but reads as a stray outline on a sidebar row — and at
        // dark-theme contrast it outshouts the selected row it sits next to.
        // Same fill the rows already hover to, matching ProjectSwitcher's list.
        "ring-offset-0 data-highlighted:border-transparent data-highlighted:bg-fill-hover data-highlighted:ring-0",
        className,
      )}
      // The two branches take the same handlers typed against different
      // elements — quill's option renders a button of its own, so what the
      // callers pass is a button's props either way.
      {...(rest as ComponentProps<typeof AutocompleteItem>)}
    >
      {children}
    </AutocompleteItem>
  );
}

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
  const spacesLayout = useChannelsLayout();
  const noun = spacesLayout ? "space" : "channel";
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
      // Unscope immediately if this was the current channel — otherwise the
      // sidebar renders a dead id (and new tasks file against it) until the
      // channels list refetches. useCurrentChannel is the backstop.
      if (useCurrentChannelStore.getState().currentChannelId === channel.id) {
        resetCurrentChannel();
      }
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
      toast.error(`Couldn't delete ${noun}`, {
        description: error instanceof Error ? error.message : String(error),
      });
      return false;
    }
  };

  const actions: ChannelActionItem[] = [
    {
      key: "star",
      label: isStarred ? `Unstar ${noun}` : `Star ${noun}`,
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
      label: `Rename ${noun}…`,
      icon: <PencilSimpleIcon size={14} />,
      separatorBefore: true,
      onSelect: () => setRenameOpen(true),
    },
    {
      key: "delete",
      label: `Delete ${noun}…`,
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

// One channel in the list: a "# name" row that opens its sidebar.
// No expansion — the channel's surfaces live in the in-channel top nav.
function ChannelSection({
  channel,
  isUnread,
  hotkeySlot,
}: {
  channel: Channel;
  /** Bolds the name: activity here the viewer hasn't seen. */
  isUnread?: boolean;
  /** ⌘1-9 slot, shown as a hint while the row isn't hovered. */
  hotkeySlot?: number;
}) {
  const spacesLayout = useChannelsLayout();
  const noun = spacesLayout ? "space" : "channel";
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const openChannel = useOpenChannel();
  const base = `/website/${channel.id}`;
  // Highlight the row whenever any of the channel's routes is open.
  const isActive = pathname === base || pathname.startsWith(`${base}/`);
  // Lifted so the hover button group stays visible while the menu is open.
  const [menuOpen, setMenuOpen] = useState(false);
  // The "+" dropdown (New task / New canvas). Keeps the hover actions pinned
  // while open.
  const [newMenuOpen, setNewMenuOpen] = useState(false);
  const { reveal, hoverProps, focusProps } = useOverflowTickerReveal();
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
    <Box className="group/chan relative" {...hoverProps}>
      {/* A single, non-expandable row: the "# name" opens the channel sidebar.
          Right-clicking opens the same actions as the "..." menu. */}
      <ContextMenu>
        <ContextMenuTrigger
          render={
            <SpaceRowSurface
              asOption={spacesLayout}
              optionValue={channel.id}
              data-selected={isActive || undefined}
              onClick={() => openChannel(channel)}
              {...focusProps}
              className={spacesLayout ? "pl-4" : undefined}
            >
              {channelGlyph(channel.name, {
                size: 14,
                space: spacesLayout,
                weight: isUnread ? "bold" : undefined,
                className: cn(
                  "shrink-0",
                  isUnread || isActive
                    ? "text-foreground"
                    : "text-muted-foreground group-hover/button:text-foreground",
                ),
              })}
              <OverflowTickerText
                reveal={reveal}
                className={cn(
                  // mr-11 clears the two icon-xs hover buttons pinned at right-1.
                  "text-[13px] group-hover/chan:mr-11",
                  // Bold is unread's alone; full contrast is shared with the
                  // channel you're in. Either way there's no hover brighten
                  // left to do, so those rows skip it.
                  isUnread ? "font-bold" : "font-medium",
                  isUnread || isActive
                    ? "text-foreground"
                    : "text-muted-foreground group-hover/button:text-foreground",
                  menuOpen && "mr-11",
                )}
              >
                {channel.name}
              </OverflowTickerText>
              {/* `!mr-0` undoes quill's `.quill-button kbd { margin-right: -4px }`,
                  which is meant to let a shortcut hang into a button's own
                  padding. Here the row's inner span is `truncate` (overflow
                  hidden) and `ml-auto` eats every pixel of slack, so the hang
                  had nowhere to go and the last 4px of the hint was cut off. */}
              {hotkeySlot != null && (
                <Kbd className="!mr-0 ml-auto shrink-0 opacity-50 group-hover/chan:opacity-0">
                  {formatHotkey(`mod+${hotkeySlot}`)}
                </Kbd>
              )}
            </SpaceRowSurface>
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
                  openTaskInput({ channelId: channel.id });
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
              This permanently deletes the {noun} and can’t be undone.
              <ul className="list-disc ps-4">
                <li>
                  The {noun} and its{" "}
                  <span className="font-medium">CONTEXT.md</span> are deleted.
                </li>
                <li>
                  Every canvas saved in this {noun} is permanently deleted.
                </li>
                <li>
                  Filed tasks are removed from the {noun}, but the tasks
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
              Delete {noun}
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
/**
 * Opening the "me" row, shared by the row itself and the search results.
 *
 * The folder is created on first use, so every action resolves the id rather
 * than closing over it — "me" is actionable before it exists. The create is
 * shared (ensurePersonalChannel) so a row click racing its "+" menu can't
 * provision two.
 */
function useOpenPersonalChannel(): {
  ensureFolderId: () => Promise<string | undefined>;
  openPersonalChannel: () => Promise<void>;
  isCreating: boolean;
} {
  const spacesLayout = useChannelsLayout();
  const navigate = useNavigate();
  const setCurrentChannel = useCurrentChannelStore((s) => s.setCurrentChannel);
  const { channels } = useChannels();
  const { createChannel, isCreating } = useChannelMutations();

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

  const openPersonalChannel = async () => {
    const channelId = await ensureFolderId();
    if (!channelId) return;
    showChannelPane();
    setCurrentChannel(channelId);
    if (!spacesLayout) {
      void navigate({ to: "/website/$channelId", params: { channelId } });
    }
  };

  return { ensureFolderId, openPersonalChannel, isCreating };
}

/**
 * Opening a channel, shared by the tree rows and the search results. In the
 * Spaces layout this scopes the sidebar without moving the main window.
 */
function useOpenChannel(): (channel: Channel) => void {
  const spacesLayout = useChannelsLayout();
  const navigate = useNavigate();
  const setCurrentChannel = useCurrentChannelStore((s) => s.setCurrentChannel);

  return (channel: Channel) => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "nav_click",
      surface: "sidebar",
      channel_id: channel.id,
    });
    showChannelPane();
    setCurrentChannel(channel.id);
    if (!spacesLayout) {
      void navigate({
        to: "/website/$channelId",
        params: { channelId: channel.id },
      });
    }
  };
}

function PersonalChannelRow({ hotkeySlot }: { hotkeySlot?: number }) {
  const spacesLayout = useChannelsLayout();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { channels } = useChannels();
  const { ensureFolderId, openPersonalChannel, isCreating } =
    useOpenPersonalChannel();
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

  const open = openPersonalChannel;

  const newTask = async () => {
    const channelId = await ensureFolderId();
    if (!channelId) return;
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "new_task_open",
      surface: "sidebar",
      channel_id: channelId,
    });
    openTaskInput({ channelId });
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
      <SpaceRowSurface
        asOption={spacesLayout}
        // "me" is provisioned on first use, so before it exists there is no id
        // to identify the option by — its name is unique among spaces either way.
        optionValue={meFolder?.id ?? PERSONAL_CHANNEL_NAME}
        data-selected={isActive || undefined}
        disabled={isCreating}
        onClick={() => void open()}
      >
        {channelGlyph(PERSONAL_CHANNEL_NAME, {
          size: 14,
          weight: isUnread ? "bold" : undefined,
          className: cn(
            "shrink-0",
            isUnread || isActive
              ? "text-foreground"
              : "text-muted-foreground group-hover/button:text-foreground",
          ),
        })}
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
        {hotkeySlot != null && (
          <Kbd className="!mr-0 ml-auto shrink-0 opacity-50 group-hover/chan:opacity-0">
            {formatHotkey(`mod+${hotkeySlot}`)}
          </Kbd>
        )}
      </SpaceRowSurface>
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
// The whole header row is the trigger. Its section glyph swaps to a down/right
// disclosure caret on hover or keyboard focus while keeping Starred and Spaces
// distinct at rest.
function ChannelGroup({
  sectionId,
  label,
  className,
  flat,
  keepMounted = true,
  icon,
  children,
}: {
  sectionId: string;
  label: string;
  className?: string;
  /** Layout-only: removes the legacy tree indent; rows apply their own inset. */
  flat?: boolean;
  /**
   * Off under the layout: a kept-mounted collapsed row is still an Autocomplete
   * option, so ↓ would walk onto spaces the user has folded away. Paying the
   * rebuild on expand is better than highlighting a row nobody can see.
   */
  keepMounted?: boolean;
  icon: ReactNode;
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
          <span className="group-hover/group-trigger:hidden group-focus-visible/group-trigger:hidden">
            {icon}
          </span>
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
      <Collapsible.Panel keepMounted={keepMounted}>
        <div className={cn(!flat && "pl-5")}>{children}</div>
      </Collapsible.Panel>
    </Collapsible.Root>
  );
}

// The channel list — the list pane of the sidebar slider. The private "#me"
// channel is pinned at the top; starred channels surface in their own section
// so the ones you use most stay in reach; the rest sit under a "Channels"
// label. Creating anything goes through the floating ChannelsFab, mounted by
// the sidebar outside this scroll region.
export function ChannelsList() {
  const { channels: allChannels, isLoading } = useChannels();
  const { starredRefToShortcutId } = useChannelStars();
  // ChannelHotkeys owns the keys these slots describe; sharing the derivation
  // keeps the advertised key and the key that fires in agreement — including
  // the fact that it only binds them under the layout, so off it the list
  // advertises nothing.
  const { slotFor } = useStarredChannelSlots();
  // Search and the shortcut hints belong to the slider, where this list is a
  // pane you switch channels from. The alpha still renders it as a plain tree.
  const channelsLayout = useChannelsLayout();

  const isUnread = useIsChannelUnread();

  const [query, setQuery] = useState("");
  const normalizedQuery = channelsLayout ? query.trim().toLowerCase() : "";
  const matches = (name: string) =>
    !normalizedQuery || name.toLowerCase().includes(normalizedQuery);

  // The "me" folder renders as the pinned personal row, not a shared channel.
  const me = allChannels.find((c) => c.name === PERSONAL_CHANNEL_NAME);
  const channels = allChannels.filter((c) => c.name !== PERSONAL_CHANNEL_NAME);
  const starred = channels.filter((c) => starredRefToShortcutId.has(c.path));
  const others = channels.filter((c) => !starredRefToShortcutId.has(c.path));

  // Searching collapses the sections into one flat list: the group labels only
  // stand between you and the row you already named, and an empty "Starred"
  // heading reads as a result that isn't there.
  const searchResults = channels.filter((c) => matches(c.name));
  const meMatches = matches(PERSONAL_CHANNEL_NAME);
  const noMatches =
    normalizedQuery !== "" && !meMatches && !searchResults.length;

  // The option values, in the order the rows below render them. The rows are
  // elements rather than a rendered collection, but Autocomplete still needs the
  // list to map a highlight index onto — without it the first ArrowDown after a
  // keystroke is swallowed re-establishing the highlight it already shows.
  // A collapsed group renders no rows, so it contributes none.
  const collapsedSections = useSidebarStore((s) => s.collapsedSections);
  // "me" is provisioned on first use; before it exists it has no id to go by.
  const meValue = me?.id ?? PERSONAL_CHANNEL_NAME;
  const optionValues = normalizedQuery
    ? [
        ...(meMatches ? [meValue] : []),
        ...searchResults.map((channel) => channel.id),
      ]
    : [
        meValue,
        ...(collapsedSections.has(STARRED_SECTION_ID)
          ? []
          : starred.map((channel) => channel.id)),
        ...(collapsedSections.has(CHANNELS_SECTION_ID)
          ? []
          : others.map((channel) => channel.id)),
      ];

  // Coming back from a space, the list is what you came here to browse — so the
  // search box takes focus and any previous query is selected, ready to be typed
  // over. Only on the transition: a cold start rests on the channel pane, and
  // re-focusing on every render would steal focus from the rows themselves.
  const pane = useChannelPaneStore((s) => s.pane);
  const previousPane = useRef(pane);
  const searchRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    const cameFromChannel = previousPane.current === "channel";
    previousPane.current = pane;
    if (!channelsLayout || pane !== "list" || !cameFromChannel) return;
    const input = searchRef.current;
    if (!input) return;
    input.focus();
    // Autocomplete leaves its highlight on the row you opened and exposes no
    // way to move it, so the pane would come back mid-list. Home is the key it
    // listens for; sending it is how the list reopens at the top.
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Home", bubbles: true }),
    );
    // After Home, so the caret it parks at the start doesn't undo the selection.
    input.select();
  }, [pane, channelsLayout]);

  const rows = normalizedQuery ? (
    <>
      {meMatches && <PersonalChannelRow />}
      {searchResults.map((channel) => (
        <ChannelSection
          key={channel.id}
          channel={channel}
          isUnread={isUnread(channel.name)}
        />
      ))}
      {noMatches && (
        <Empty className="px-2 py-1 text-subtle-foreground text-xs">
          <EmptyHeader className="text-left">
            No {channelsLayout ? "spaces" : "channels"} match “{query.trim()}”.
          </EmptyHeader>
        </Empty>
      )}
    </>
  ) : (
    <>
      <PersonalChannelRow
        hotkeySlot={channelsLayout && me ? slotFor(me) : undefined}
      />

      {starred.length > 0 && (
        <ChannelGroup
          sectionId={STARRED_SECTION_ID}
          label="Starred"
          flat={channelsLayout}
          keepMounted={!channelsLayout}
          icon={<StarIcon size={14} />}
        >
          {starred.map((channel) => (
            <ChannelSection
              key={channel.id}
              channel={channel}
              isUnread={isUnread(channel.name)}
              hotkeySlot={channelsLayout ? slotFor(channel) : undefined}
            />
          ))}
        </ChannelGroup>
      )}

      <ChannelGroup
        sectionId={CHANNELS_SECTION_ID}
        label={channelsLayout ? "Spaces" : "Channels"}
        flat={channelsLayout}
        keepMounted={!channelsLayout}
        icon={
          channelsLayout ? <CubeFocusIcon size={14} /> : <HashIcon size={14} />
        }
      >
        {!isLoading && channels.length === 0 && (
          <Empty className="px-2 py-1 text-subtle-foreground text-xs">
            <EmptyHeader className="text-left">
              No {channelsLayout ? "spaces" : "channels"} yet.
            </EmptyHeader>
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
    </>
  );

  // Bottom padding clears the floating create button (ChannelsFab), so the last
  // channel stays reachable at full scroll.
  const scrollClass =
    "scroll-mask-4 min-h-0 flex-1 overflow-y-auto px-2 pt-2 pb-16";
  // quill sizes its list as a popup — a ~250px cap and its own 4px padding —
  // and ships it unlayered, so plain utilities lose to it however they're
  // ordered. Here the list *is* the pane, so the cap has to go and the pane's
  // own padding has to win: `!` is what outranks an unlayered rule.
  const listClass = cn(
    "flex flex-col gap-px",
    "!max-h-none !px-2 !pt-2 !pb-16",
    scrollClass,
  );

  const body = (
    <Flex direction="column" className="h-full min-h-0">
      {channelsLayout && (
        <Box className="shrink-0 px-2 pt-1">
          <AutocompleteInput
            ref={searchRef}
            placeholder="Search spaces…"
            aria-label="Search spaces"
            showSearchIcon={false}
            className="h-7 text-[13px]"
            onKeyDown={(event) => {
              // Base UI's clear is a tabIndex=-1 decoration, so Escape is the
              // keyboard way out of a query. With the box already empty there's
              // nothing to clear, and Escape belongs to whoever is listening
              // above (closing the sidebar, dismissing a dialog).
              if (event.key !== "Escape" || query === "") return;
              event.preventDefault();
              event.stopPropagation();
              setQuery("");
            }}
          >
            {/* Rendered here rather than via `showClear` so it can be given a
                tab stop: quill passes no props to the one it renders itself. */}
            <AutocompleteClear
              tabIndex={0}
              aria-label="Clear search"
              onClick={() => setQuery("")}
            />
          </AutocompleteInput>
        </Box>
      )}
      {channelsLayout ? (
        // Every row is an option, filtered or not, so ↑/↓/⏎ work the moment the
        // pane opens rather than only once you've typed something.
        <AutocompleteList className={listClass}>{rows}</AutocompleteList>
      ) : (
        <Flex direction="column" gap="px" className={scrollClass}>
          {rows}
        </Flex>
      )}
    </Flex>
  );

  return (
    // One shared provider groups every row tooltip so that once one shows,
    // moving to the next row reveals its tooltip instantly (no re-delay).
    <TooltipProvider delay={600}>
      {channelsLayout ? (
        // The rows render as elements — they're a tree of collapsible groups,
        // not a flat collection — so `items` carries their values alone, in the
        // same order. Filtering is ours (hence `filter={null}`; Base UI's matcher
        // would run over an already-narrowed set). `inline` renders the list in
        // the pane instead of a popup, and `defaultOpen` keeps it rendered
        // without a trigger to open it.
        <Autocomplete<string>
          inline
          // Pinned open, not `defaultOpen`: picking a row closes an ordinary
          // combobox, and a closed one stops answering the arrow keys. This list
          // is the pane itself — there is nothing to close, and coming back from
          // a space has to find it live.
          open
          items={optionValues}
          filter={null}
          value={query}
          autoHighlight="always"
          // Without this the highlight resets on pointer-leave, and "always"
          // then snaps it back to the first row — so drifting the mouse across
          // the gap between two rows threw the keyboard back to the top.
          keepHighlight
          onValueChange={(value, eventDetails) => {
            // Selecting a row would otherwise write the row's value back into
            // the input; only what the user types moves the query.
            if (eventDetails.reason !== "input-change") return;
            if (typeof value === "string") setQuery(value);
          }}
        >
          {body}
        </Autocomplete>
      ) : (
        body
      )}
    </TooltipProvider>
  );
}
