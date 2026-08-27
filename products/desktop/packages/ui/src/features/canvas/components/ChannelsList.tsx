import { Collapsible } from "@base-ui/react/collapsible";
import {
  ArrowRightIcon,
  CaretDownIcon,
  CaretRightIcon,
  DotsThreeIcon,
  LinkIcon,
  PencilSimpleIcon,
  PlusIcon,
  StarIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import {
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Autocomplete,
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
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import {
  ChannelItemHoverCard,
  SpaceHoverCard,
} from "@posthog/ui/features/canvas/components/ChannelItemHoverCard";
import type { ChannelActionItem } from "@posthog/ui/features/canvas/components/channelActions";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { RenameChannelModal } from "@posthog/ui/features/canvas/components/RenameChannelModal";
import { SidebarSearchHeader } from "@posthog/ui/features/canvas/components/SidebarSearchHeader";
import type { SpacePreviewPayload } from "@posthog/ui/features/canvas/components/SpacePreview";
import {
  TaskRowContextMenu,
  type TaskRowMenuProps,
} from "@posthog/ui/features/canvas/components/TaskRowMenu";
import { useBlockedSessionCount } from "@posthog/ui/features/canvas/hooks/useBlockedSessionCount";
import { useChannelStarToggle } from "@posthog/ui/features/canvas/hooks/useChannelStars";
import {
  type Channel,
  useChannelMutations,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useChannelTaskStatus } from "@posthog/ui/features/canvas/hooks/useChannelTaskStatus";
import {
  NO_TASKS,
  type SpaceTasks,
  usePrefetchSpaceTasks,
  useRecentSpaceTasks,
} from "@posthog/ui/features/canvas/hooks/useRecentSpaceTasks";
import {
  SpaceTaskActionsProvider,
  useSpaceTaskActions,
  useSpaceTaskActionsContext,
} from "@posthog/ui/features/canvas/hooks/useSpaceTaskActions";
import { useStarredChannelSlots } from "@posthog/ui/features/canvas/hooks/useStarredChannelSlots";
import {
  PERSONAL_CHANNEL_LABEL,
  PERSONAL_CHANNEL_NAME,
} from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useIsChannelUnread } from "@posthog/ui/features/canvas/hooks/useUnreadChannels";
import { useUnreadSessionCount } from "@posthog/ui/features/canvas/hooks/useUnreadSessionCount";
import {
  keepListForRoute,
  showChannelPane,
  useChannelPaneStore,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import {
  resetCurrentChannel,
  useCurrentChannelStore,
} from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { requestSidebarSearchFocus } from "@posthog/ui/features/canvas/stores/sidebarSearchStore";
import { useSpaceTreeStore } from "@posthog/ui/features/canvas/stores/spaceTreeStore";
import { copyChannelLink } from "@posthog/ui/features/canvas/utils/copyChannelLink";
import { formatHotkey } from "@posthog/ui/features/command/keyboard-shortcuts";
import {
  TaskBadgeStack,
  TaskStatusDot,
  TaskStatusTooltips,
} from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import {
  DOT_TONE_VAR,
  taskDot,
} from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { HandoffTaskDialog } from "@posthog/ui/features/task-detail/components/HandoffTaskDialog";
import {
  OverflowTickerText,
  useOverflowTickerReveal,
} from "@posthog/ui/primitives/OverflowTickerText";
import { toast } from "@posthog/ui/primitives/toast";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import { Box, Flex } from "@radix-ui/themes";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import {
  type ComponentProps,
  Fragment,
  memo,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  type SyntheticEvent as ReactSyntheticEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { hostClient } from "../hostClient";

const channelsLog = logger.scope("channels");

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
          "w-full min-w-0 justify-start gap-2 data-selected:text-foreground",
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
        // name truncate, exactly as they do in the button above. Its `truncate`
        // also clips, which would cut off the disclosure's hit box where that
        // hangs past the wrapper; every child that needs clipping does its own.
        "[&>span]:w-full [&>span]:gap-2 [&>span]:overflow-visible",
        // An icon's own colour lives on its `<svg>`, but quill repaints a
        // highlighted option's contents down to the `<path>` that `fill:
        // currentColor` resolves against, which drops every badge to the row's
        // colour. Sending the marks back to their icon keeps a pinned row's pin
        // and a status badge's tone under the pointer and the keyboard.
        "[&_svg_*]:text-inherit!",
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

/**
 * A row in the flat list the keyboard walks. The rows render as a tree, but
 * Autocomplete only knows a sequence — so the tree's shape lives here, as the
 * parent each task hangs off and the space each row belongs to.
 */
type SpaceTreeNode =
  | { kind: "section"; value: string; sectionId: string }
  | {
      kind: "space";
      value: string;
      spaceId: string | undefined;
      /** The heading above it, absent while searching — there are none then. */
      parentValue: string | undefined;
    }
  | { kind: "task"; value: string; spaceId: string; parentValue: string };

/** How long the pointer has to rest on a space before its sessions are warmed. */
const SESSION_PREFETCH_DELAY_MS = 250;

/**
 * A row label's resting colour and the two states that bring it up to full
 * contrast: the pointer on the row, and the keyboard's highlight on it.
 *
 * The highlight needs saying here. quill brings a highlighted option's contents
 * to `--foreground` with `.quill-autocomplete__item[data-highlighted] *`, but
 * that rule is in the components layer, so any label carrying a colour utility
 * of its own outranks it and stays muted under the keyboard while brightening
 * under the pointer.
 */
/**
 * What the keyboard calls the personal row before the channel list has loaded.
 *
 * The row is provisioned server-side with the first fetch, so until then it has
 * no id to be identified by. The rendered row and the keyboard's flat node list
 * both have to spell this, and they have to agree.
 */
const PERSONAL_ROW_VALUE = "personal-row";

const ROW_LABEL_TONE =
  "text-muted-foreground group-hover/button:text-foreground group-data-highlighted/button:text-foreground";

/**
 * Walk Autocomplete's highlight by synthesizing the arrow keys it already
 * listens for. There is no API to set the highlighted row, and the input keeps
 * focus throughout — it is the list's only cursor. Base UI holds the index in a
 * ref, so a run of dispatches steps that many rows rather than collapsing into
 * one.
 */
function moveHighlight(
  input: HTMLInputElement,
  key: "ArrowUp" | "ArrowDown",
  steps: number,
): void {
  for (let step = 0; step < steps; step++) {
    input.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
  }
}

/**
 * There are sessions in this space that want something from you. Sits after the
 * name, and is the same 8px yellow the session rows' own dots are: it stands for
 * those rows, so it has to look like one of them rather than a badge about them.
 *
 * One dot however many sessions, because the row's job here is to say "there is
 * something in here", and a count you can't act on without opening the space is
 * a number for its own sake. Nothing at all when the space is quiet — the only
 * mark on the row allowed to be absent, which is what makes it worth a glance.
 */
function SpaceAttentionDot({
  count,
  tone = "attention",
  faded,
  className,
}: {
  count: number;
  /**
   * Which of the two things the space is saying. Blue is the session rows' own
   * "blocked on you", so a space whose sessions are waiting on an answer shows
   * that alongside the yellow rather than folding it in — one of these you can
   * clear from here, the other you have to go in and read.
   */
  tone?: "attention" | "blocked";
  /**
   * The sessions it stands for are on screen, wearing dots of their own. It
   * still marks which space they belong to, so it stays — at a weight that
   * leaves the ones you can act on the brighter of the two.
   */
  faded?: boolean;
  /** The row's hover margin, when the dot is what ends its content. */
  className?: string;
}) {
  if (count === 0) return null;
  const sessions = `${count} ${count === 1 ? "session" : "sessions"}`;
  return (
    <span
      // The dot is one mark whatever the number, but the number is still the
      // useful fact for anyone who can't see it.
      aria-label={
        tone === "blocked"
          ? `${sessions} waiting on you`
          : `${sessions} waiting`
      }
      role="img"
      className={cn(
        "size-2 shrink-0 rounded-full",
        faded && "opacity-40",
        className,
      )}
      // The session rows' own tone, off the one table that decides what a dot's
      // colour means, so the space and the rows inside it can't drift.
      style={{
        backgroundColor:
          tone === "blocked" ? DOT_TONE_VAR.blue : "var(--primary)",
      }}
    />
  );
}

/**
 * The tree's disclosure caret, in its own fixed slot ahead of the space glyph.
 * Always drawn: a control that only appears on hover moves the row's contents
 * as the pointer crosses the list, and leaves the tree invisible to anyone who
 * hasn't hovered a row yet.
 *
 * Not a `<button>` — the row around it already is one (quill's option renders a
 * button too), and nesting buttons is invalid. Keyboard users get ArrowRight /
 * ArrowLeft on the row instead, which is the point of the tree.
 */
function SpaceDisclosure({
  expanded,
  spaceName,
  onToggle,
}: {
  expanded: boolean;
  spaceName: string;
  onToggle: () => void;
}) {
  const toggle = (event: ReactSyntheticEvent) => {
    // The row opens the space; the caret only opens the tree, so its events
    // stop before they reach the row underneath.
    event.preventDefault();
    event.stopPropagation();
    onToggle();
  };

  return (
    // biome-ignore lint/a11y/useSemanticElements: a nested clickable inside the row's own <button>
    <span
      role="button"
      // Out of the tab order on purpose: the search box is the pane's single
      // focus holder, and a stop per space would bury it.
      tabIndex={-1}
      aria-expanded={expanded}
      aria-label={`${expanded ? "Collapse" : "Expand"} ${spaceName}`}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={toggle}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") toggle(event);
      }}
      className={cn(
        "relative flex size-3.5 shrink-0 items-center justify-center",
        // Barely lit while closed, because a column of carets down the list
        // would out-draw the names beside it. Open, it comes up to full: it is
        // the only thing saying this space is the one the rows below belong to.
        //
        // Forced, and aimed at the glyph's descendants, because quill repaints
        // a highlighted option's contents (see `ROW_LABEL_TONE`) and that rule's
        // `*` reaches the icon's `<path>`, which is what `fill: currentColor`
        // resolves against, so a colour on this span or on the `<svg>` still
        // leaves the mark drawn in the row's colour.
        expanded ? "**:text-foreground!" : "**:text-muted-foreground/30!",
        "hover:**:text-foreground!",
        // A 24px hit target on a 14px mark, hung off the caret's left so it
        // reaches the row's edge and stops before the name. Absolute rather than
        // padding, so the caret keeps its slot and nothing in the row moves.
        "before:-left-8 before:absolute before:inset-auto before:size-6 before:content-['']",
        "before:-translate-y-1/2 before:top-1/2 before:rounded-[calc(var(--radius)-5px)]",
        "hover:before:bg-fill-hover",
      )}
    >
      {expanded ? <CaretDownIcon size={10} /> : <CaretRightIcon size={10} />}
    </span>
  );
}

/**
 * Opening a session from the tree: load it in the main window and leave the
 * sidebar where it is.
 *
 * Picking a session out of the tree is not a request to go into its space — you
 * are browsing across spaces, and sliding into one would take the tree you are
 * reading off the screen. Entering a space is what its own row is for.
 */
function useOpenSpaceTask(): (spaceId: string, taskId: string) => void {
  const navigate = useNavigate();
  const setCurrentChannel = useCurrentChannelStore((s) => s.setCurrentChannel);

  return (spaceId, taskId) => {
    keepListForRoute(spaceId);
    // Still scoped: the space is where the session lives, so anything that then
    // asks for the channel pane opens on the right one.
    setCurrentChannel(spaceId);
    void navigate({
      to: "/spaces/$channelId/tasks/$taskId",
      params: { channelId: spaceId, taskId },
    });
  };
}

/**
 * One session under an expanded space, a leaf of the tree.
 *
 * Wears the space's own session list vocabulary: the state dot on the left, the
 * identity badges on the right, and the hover card and right-click menu that
 * list gives the same task. The row itself is hand-built rather than
 * `ChannelItemRow`, which is a `SidebarItem` button and so cannot be an
 * Autocomplete option, and being one is what keeps ↑/↓/⏎ walking the tree.
 */
const SpaceTaskRow = memo(function SpaceTaskRow({
  item,
  spaceId,
  asOption,
}: {
  item: ChannelItemModel;
  spaceId: string;
  asOption: boolean;
}) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const openTask = useOpenSpaceTask();
  // No PR lookup here: that is a host round trip per row, and the tree can show
  // a dozen spaces' worth of rows at once.
  const status = useChannelTaskStatus(item, { withPrStatus: false });
  const isActive = pathname.endsWith(`/tasks/${item.id}`);
  const actions = useSpaceTaskActionsContext();
  // A boolean rather than the value itself, so a keypress re-renders only the
  // two rows whose answer changed.
  const isHighlighted = useSpaceTreeStore(
    (s) => s.highlightedValue === item.key,
  );

  const [handoffOpen, setHandoffOpen] = useState(false);
  // Only the owner may hand a task off; the API 404s it for anyone else.
  const currentUser = useCurrentUser();
  const canHandoff =
    item.kind === "task" &&
    item.task != null &&
    item.authorUser?.id != null &&
    currentUser.data?.id === item.authorUser.id;

  // The tree only lists sessions, so this is always the task menu. Rename is
  // the one item the space's own list has and this doesn't, because it edits in
  // place and there is no inline editor on a row the keyboard is walking.
  //
  // Memoized because it travels to the shared preview card as the trigger's
  // payload, which is written to the card's store whenever its identity changes.
  const menu: TaskRowMenuProps = useMemo(
    () => ({
      kind: "task",
      id: item.id,
      title: item.title,
      isPinned: item.pinned,
      task: item.task ?? undefined,
      // Ticks the space the session is already in, inside "File to…".
      channelId: spaceId,
      onAddToCommandCenter: actions.commandCenterAssigner(item.id),
      onTogglePin: () => actions.togglePin(item),
      onArchive: () => actions.archive(item),
      ...(canHandoff ? { onHandoff: () => setHandoffOpen(true) } : {}),
    }),
    // canHandoff rides on the currentUser query, so it belongs in deps for a
    // sign-in refresh to re-evaluate.
    [item, spaceId, actions, canHandoff],
  );

  const row = (
    <SpaceRowSurface
      asOption={asOption}
      optionValue={item.key}
      data-selected={isActive || undefined}
      onClick={() => openTask(spaceId, item.id)}
      // A step in from its space's name, clear of the guide that runs between
      // the two columns.
      className="pl-8"
    >
      {/* The dot belongs to the title, not to the row: its own tighter gap
          keeps them one mark rather than two columns. */}
      <span className="flex min-w-0 items-center gap-1.5">
        <TaskStatusDot dot={taskDot(status ?? {})} />
        <span
          className={cn(
            "truncate text-[13px]",
            isActive ? "text-foreground" : ROW_LABEL_TONE,
          )}
        >
          {item.title}
        </span>
      </span>
      {status && (
        <span className="ml-auto flex shrink-0 items-center gap-1">
          <TaskBadgeStack status={status} pinned={item.pinned} />
        </span>
      )}
    </SpaceRowSurface>
  );

  return (
    <TaskRowContextMenu menu={menu}>
      {/* One tooltip provider per row, shared by its dot and badges so moving
          between them doesn't re-wait the open delay. */}
      <TaskStatusTooltips>
        {/* Not on the row you are already in: ⏎ opens the session and leaves
            the highlight where it was, so the card would sit over the session
            it just opened. */}
        <ChannelItemHoverCard
          item={item}
          menu={menu}
          highlighted={isHighlighted && !isActive}
        >
          {row}
        </ChannelItemHoverCard>
        {canHandoff && item.task ? (
          <HandoffTaskDialog
            task={item.task}
            open={handoffOpen}
            onOpenChange={setHandoffOpen}
          />
        ) : null}
      </TaskStatusTooltips>
    </TaskRowContextMenu>
  );
});

/** How the keyboard and the row itself name the "View all" leaf. */
const viewAllValue = (spaceId: string) => `view-all:${spaceId}`;

/**
 * Whether a space has sessions the tree isn't showing. The list and the
 * keyboard's flat node list both ask, and they have to agree: a "View all" row
 * the keyboard doesn't know about throws the highlight index off from there
 * down.
 */
function hasViewAllRow(tasks: SpaceTasks): boolean {
  return tasks.items.length > 0 && tasks.total > tasks.items.length;
}

/**
 * The last leaf under an expanded space: how many sessions the tree isn't
 * showing, and the way into the space that has them. Quieter than a session row
 * at rest, because it leads out of the tree rather than being another thing in
 * it, and it comes up to full contrast under the pointer or the keyboard.
 */
function ViewAllRow({
  spaceId,
  remaining,
  asOption,
  onOpenSpace,
}: {
  spaceId: string;
  remaining: number;
  asOption: boolean;
  onOpenSpace: () => void;
}) {
  return (
    <SpaceRowSurface
      asOption={asOption}
      optionValue={viewAllValue(spaceId)}
      onClick={onOpenSpace}
      className={cn("pl-8 text-[13px]", ROW_LABEL_TONE)}
    >
      {/* The arrow takes the slot a session's status dot has, so the guide's
          turn lands on that column and the label starts where the titles above
          it do. */}
      <span className="flex min-w-0 items-center gap-0.5">
        <ArrowRightIcon
          aria-hidden
          size={10}
          className="relative top-[-0.5px] left-[-3px] shrink-0 text-foreground/20"
        />
        <span className="truncate">view all</span>
      </span>
      <span className="shrink-0 text-muted-foreground/50 text-xxs">
        {remaining}
      </span>
    </SpaceRowSurface>
  );
}

/**
 * Runs from the space's caret down the sessions beneath it, so a long list still
 * reads as belonging to the space above rather than to the list at large.
 *
 * Positioned rather than a border, on the caret's own centre: it lines up with
 * the glyph that opened the space, not the text beside it, and it costs the rows
 * none of their width. The half-pixel is the centre — a 1px line either side of
 * it would sit off the glyph by the same amount.
 */
function SpaceTreeGuide() {
  return (
    <span
      aria-hidden
      className="pointer-events-none absolute inset-y-0 left-[14.5px] w-px bg-foreground/20"
    />
  );
}

/**
 * How the guide ends when the space has more than the tree is showing: it turns
 * into the "View all" row instead of running past it. The turn says this is the
 * end of the branch, and points at the row that leads out of it.
 *
 * `-top-px` and the matching height close the flex gap above, so the turn reads
 * as the same line rather than a mark that starts below it. The width carries it
 * from the guide's column to the one the status dots keep, where the row's arrow
 * picks it up.
 */
function SpaceTreeGuideEnd() {
  return (
    <span
      aria-hidden
      className="-top-px pointer-events-none absolute left-[14.5px] h-[calc(50%+1px)] w-[16.5px] rounded-bl-md border-foreground/20 border-b border-l"
    />
  );
}

/**
 * The sessions under one expanded space, or the fact that it has none. The
 * empty line is not an option: ↓ walking onto "No sessions yet" would be a dead
 * end.
 */
function SpaceTaskRows({
  spaceId,
  tasks,
  asOption,
  onOpenSpace,
}: {
  spaceId: string;
  tasks: SpaceTasks;
  asOption: boolean;
  /** Where "View all" goes: the space itself, in the sidebar. */
  onOpenSpace: () => void;
}) {
  if (tasks.items.length === 0) {
    return (
      <div className="relative">
        <SpaceTreeGuide />
        <div className="py-1 pl-12 text-subtle-foreground text-xs">
          No sessions yet
        </div>
      </div>
    );
  }
  return (
    // The rows were siblings in the list's own flex column, so the wrappers that
    // give the guide something to hang off have to keep their spacing. The
    // sessions get their own, because the guide runs their full height and stops
    // where the turn into "View all" begins.
    <div className="flex flex-col gap-px">
      <div className="relative flex flex-col gap-px">
        <SpaceTreeGuide />
        {tasks.items.map((item) => (
          <SpaceTaskRow
            key={item.key}
            item={item}
            spaceId={spaceId}
            asOption={asOption}
          />
        ))}
      </div>
      {hasViewAllRow(tasks) && (
        <div className="relative">
          <SpaceTreeGuideEnd />
          <ViewAllRow
            spaceId={spaceId}
            remaining={tasks.total - tasks.items.length}
            asOption={asOption}
            onOpenSpace={onOpenSpace}
          />
        </div>
      )}
    </div>
  );
}

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
  const { isStarred, toggleStar } = useChannelStarToggle(channel);

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
          hostClient().channelTasks.unfile.mutate({ taskId: t.taskId }),
        ),
      ]);

      // Deleting the channel removes its per-user stars server-side with it.
      await deleteChannel(channel.id);
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
      if (pathname.startsWith(`/spaces/${channel.id}`)) {
        void navigate({ to: "/spaces" });
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

  // Memoized because it travels to the shared preview card as the space
  // trigger's payload, which is written to the card's store whenever its
  // identity changes.
  const actions: ChannelActionItem[] = useMemo(
    () => [
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
    ],
    [channel.id, isStarred, noun, toggleStar],
  );

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

// One channel in the list: a "# name" row that opens its sidebar, above the
// space's most recent tasks when it's expanded. The channel's other surfaces
// live in the in-channel top nav.
const ChannelSection = memo(
  function ChannelSection({
    channel,
    isUnread,
    unreadSessions = 0,
    blockedSessions = 0,
    hotkeySlot,
    expanded = false,
    tasks,
    onToggleExpanded,
  }: {
    channel: Channel;
    /** Bolds the name: activity here the viewer hasn't seen. */
    isUnread?: boolean;
    /** How many sessions inside are unread. A number, so the memo can compare it. */
    unreadSessions?: number;
    /** How many sessions inside are waiting on an answer from you. */
    blockedSessions?: number;
    /** ⌘1-9 slot, shown as a hint while the row isn't hovered. */
    hotkeySlot?: number;
    expanded?: boolean;
    /** The space's recent sessions and its total; only read while expanded. */
    tasks?: SpaceTasks;
    /**
     * Absent while searching, where the list is flat. Takes the space id rather
     * than closing over it, so the list can hand every row the same function and
     * the memo below survives a parent render.
     */
    onToggleExpanded?: (spaceId: string) => void;
  }) {
    const spacesLayout = useChannelsLayout();
    const noun = spacesLayout ? "space" : "channel";
    const pathname = useRouterState({ select: (s) => s.location.pathname });
    const openChannel = useOpenChannel();
    const base = `/spaces/${channel.id}`;
    // Highlight the row whenever any of the channel's routes is open.
    const isActive = pathname === base || pathname.startsWith(`${base}/`);
    // Lifted so the hover button group stays visible while the menu is open.
    const [menuOpen, setMenuOpen] = useState(false);
    const { reveal, hoverProps, focusProps } = useOverflowTickerReveal();
    const hasAttention = unreadSessions > 0 || blockedSessions > 0;
    const prefetchSessions = usePrefetchSpaceTasks();
    const prefetchTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
      undefined,
    );
    useEffect(() => () => clearTimeout(prefetchTimer.current), []);
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

    const newTask = () => {
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "new_task_open",
        surface: "sidebar",
        channel_id: channel.id,
      });
      openTaskInput({ channelId: channel.id });
    };

    // A boolean rather than the value itself, so a keypress re-renders only the
    // two rows whose answer changed. The row's autocomplete value is the space
    // id, which is what the keyboard's highlight holds.
    const isHighlighted = useSpaceTreeStore(
      (s) => s.highlightedValue === channel.id,
    );

    // What the shared card says about this space. Memoized because a new
    // identity is written to the card's store again, and the counts change on
    // every feed poll.
    const preview: SpacePreviewPayload = useMemo(
      () => ({
        channel,
        unreadSessions,
        blockedSessions,
        actions,
      }),
      [channel, unreadSessions, blockedSessions, actions],
    );

    const glyph = channelGlyph(channel.name, {
      personal: channel.channelType === "personal",
      size: 14,
      space: spacesLayout,
      weight: isUnread ? "bold" : undefined,
      className: cn(
        "shrink-0",
        isUnread || isActive
          ? "text-foreground"
          : "text-muted-foreground group-hover/button:text-foreground",
      ),
    });

    return (
      <>
        <Box
          className="group/chan relative"
          {...hoverProps}
          // Warm the sessions while the pointer is on the row, so opening the
          // space is a render rather than a round trip.
          onPointerEnter={() => {
            hoverProps.onPointerEnter();
            // Only once the pointer rests. Arrowing through the tree scrolls
            // rows under a stationary cursor, and prefetching on the enter
            // itself turned every keypress into a fetch per row it passed.
            clearTimeout(prefetchTimer.current);
            prefetchTimer.current = setTimeout(
              () => prefetchSessions(channel.id),
              SESSION_PREFETCH_DELAY_MS,
            );
          }}
          onPointerLeave={() => {
            hoverProps.onPointerLeave();
            clearTimeout(prefetchTimer.current);
          }}
        >
          {/* The "# name" opens the channel sidebar; the glyph doubles as the
            caret that opens the space's recent tasks below it. Right-clicking
            opens the same actions as the "..." menu, and resting on it opens
            the space's card — the same popup the sessions under it use, so
            crossing between them swaps contents rather than reopening. */}
          {/* Not on the space you are already in: opening it leaves the
              highlight where it was, so the card would sit over the space it
              just opened. */}
          <SpaceHoverCard
            space={preview}
            highlighted={isHighlighted && !isActive}
          >
            <ContextMenu>
              <ContextMenuTrigger
                render={
                  <SpaceRowSurface
                    asOption={spacesLayout}
                    optionValue={channel.id}
                    // An open space hands the fill to the session under it: the row
                    // you are in is the one the fill is for, and two of them stacked
                    // reads as two selections.
                    data-selected={(isActive && !expanded) || undefined}
                    onClick={() => openChannel(channel)}
                    {...focusProps}
                    className={spacesLayout ? "pl-2" : undefined}
                  >
                    {onToggleExpanded && (
                      <SpaceDisclosure
                        expanded={expanded}
                        spaceName={channel.name}
                        onToggle={() => onToggleExpanded(channel.id)}
                      />
                    )}
                    {glyph}
                    <OverflowTickerText
                      reveal={reveal}
                      className={cn(
                        "text-[13px]",
                        // mr-11 clears the two icon-xs hover buttons pinned at
                        // right-1. It belongs on whatever ends the row's content —
                        // put it on the name while the dot is there and the gap
                        // opens between them, carrying the dot off to the buttons.
                        !hasAttention && "group-hover/chan:mr-11",
                        // Bold is unread's alone; full contrast is shared with the
                        // channel you're in. Either way there's no hover brighten
                        // left to do, so those rows skip it.
                        isUnread ? "font-bold" : "font-medium",
                        isUnread || isActive
                          ? "text-foreground"
                          : ROW_LABEL_TONE,
                        menuOpen && !hasAttention && "mr-11",
                      )}
                    >
                      {channel.name}
                    </OverflowTickerText>
                    {/* Both dots in one slot, so the hover margin belongs to the
                      pair rather than to whichever of them happens to end the
                      row. */}
                    {hasAttention && (
                      <span
                        className={cn(
                          "flex shrink-0 items-center gap-1",
                          "group-hover/chan:mr-11",
                          menuOpen && "mr-11",
                        )}
                      >
                        {/* Blue first, because the rows below are sorted with
                          what wants you at the top — the pair reads as a
                          summary of that list, in its order. */}
                        <SpaceAttentionDot
                          count={blockedSessions}
                          tone="blocked"
                          faded={expanded}
                        />
                        <SpaceAttentionDot
                          count={unreadSessions}
                          faded={expanded}
                        />
                      </span>
                    )}
                    {/* `!mr-0` undoes quill's `.quill-button kbd { margin-right: -4px }`,
                  which is meant to let a shortcut hang into a button's own
                  padding. Here `ml-auto` takes every pixel of slack, so the
                  hang had nowhere to go and cut off the last 4px of the hint. */}
                    {/* Dropped from the row rather than faded on hover: the label
                  already reserves mr-11 for the buttons that replace the hint,
                  and a hint still taking part in the row's width and its gap
                  there is what cut a starred name shorter than an unstarred
                  one. */}
                    {hotkeySlot != null && (
                      <Kbd className="!mr-0 ml-auto shrink-0 opacity-50 group-hover/chan:hidden">
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
          </SpaceHoverCard>
          {/* Hover actions stay visible while the menu is open. */}
          <div className="absolute top-1 right-1">
            <ButtonGroup>
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      variant="outline"
                      size="icon-xs"
                      aria-label={`New task in ${channel.name}`}
                      className={cn(
                        "gap-1 transition-opacity group-hover:border-border",
                        menuOpen
                          ? "opacity-100"
                          : "opacity-0 group-hover/chan:opacity-100",
                      )}
                      onClick={newTask}
                    >
                      <PlusIcon size={12} weight="bold" />
                    </Button>
                  }
                />
                <TooltipContent side="top">New task</TooltipContent>
              </Tooltip>
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
                      <span className="font-medium">CONTEXT.md</span> are
                      deleted.
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
        {expanded && (
          <SpaceTaskRows
            spaceId={channel.id}
            tasks={tasks ?? NO_TASKS}
            asOption={spacesLayout}
            onOpenSpace={() => openChannel(channel)}
          />
        )}
      </>
    );
  },
  // A space row is expensive — a context menu, two dropdowns, a tooltip and two
  // dialogs each — and there are dozens of them. Without this, expanding one
  // space rebuilt every other row: ~350-540ms per expand, in 300ms chunks that
  // blocked the keyboard. The channel object is compared by the fields the row
  // actually draws, because the channel list is polled and hands out new objects
  // on every refetch.
  (prev, next) =>
    prev.expanded === next.expanded &&
    prev.isUnread === next.isUnread &&
    prev.unreadSessions === next.unreadSessions &&
    prev.blockedSessions === next.blockedSessions &&
    prev.hotkeySlot === next.hotkeySlot &&
    prev.tasks === next.tasks &&
    prev.onToggleExpanded === next.onToggleExpanded &&
    prev.channel.id === next.channel.id &&
    prev.channel.name === next.channel.name &&
    prev.channel.starred === next.channel.starred &&
    prev.channel.channelType === next.channel.channelType &&
    prev.channel.createdBy?.uuid === next.channel.createdBy?.uuid &&
    // By content: the poll hands out a new array even when the repos are the
    // same, and the space's card draws them.
    prev.channel.repositories.length === next.channel.repositories.length &&
    prev.channel.repositories.every(
      (repo, index) => repo === next.channel.repositories[index],
    ),
);

// The user's private channel, named personal, is pinned above the shared list.
// Provisioned lazily server-side when the channel list is fetched, so the row
// only has to find it — there is no client-side create.
/**
 * Opening the personal row, shared by the row itself and the search results.
 *
 * The personal channel appears with the first channel-list fetch; until then
 * the row's actions have nothing truthful to act on, so they explain rather
 * than provision a duplicate.
 */
function useOpenPersonalChannel(): {
  ensureChannelId: () => string | undefined;
  openPersonalChannel: () => void;
} {
  const spacesLayout = useChannelsLayout();
  const navigate = useNavigate();
  const setCurrentChannel = useCurrentChannelStore((s) => s.setCurrentChannel);
  const { channels, isLoading } = useChannels();

  const ensureChannelId = (): string | undefined => {
    const meChannel = channels.find((c) => c.channelType === "personal");
    if (!meChannel) {
      channelsLog.warn("Personal space missing from the channel list", {
        channelCount: channels.length,
        isLoading,
      });
      toast.error("Couldn't open personal space", {
        description:
          "Your personal space is still loading. Try again in a moment.",
      });
      return undefined;
    }
    return meChannel.id;
  };

  const openPersonalChannel = () => {
    const channelId = ensureChannelId();
    if (!channelId) return;
    showChannelPane({ animate: true });
    setCurrentChannel(channelId);
    if (!spacesLayout) {
      void navigate({ to: "/spaces/$channelId", params: { channelId } });
    }
  };

  return { ensureChannelId, openPersonalChannel };
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
    showChannelPane({ animate: true });
    setCurrentChannel(channel.id);
    if (!spacesLayout) {
      void navigate({
        to: "/spaces/$channelId",
        params: { channelId: channel.id },
      });
    }
  };
}

const PersonalChannelRow = memo(function PersonalChannelRow({
  hotkeySlot,
  expanded = false,
  tasks,
  onToggleExpanded,
}: {
  hotkeySlot?: number;
  expanded?: boolean;
  tasks?: SpaceTasks;
  /** Absent while searching; takes the space id, like the shared rows. */
  onToggleExpanded?: (spaceId: string) => void;
}) {
  const spacesLayout = useChannelsLayout();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { channels } = useChannels();
  const { ensureChannelId, openPersonalChannel } = useOpenPersonalChannel();

  // Startup provisions #me, so `undefined` means the list has not loaded yet.
  const meChannel = channels.find((c) => c.channelType === "personal");
  const isUnread = useIsChannelUnread()(meChannel?.id);
  const unreadSessions = useUnreadSessionCount()(meChannel?.id);
  const blockedSessions = useBlockedSessionCount()(meChannel?.id);
  const isActive =
    !!meChannel &&
    (pathname === `/spaces/${meChannel.id}` ||
      pathname.startsWith(`/spaces/${meChannel.id}/`));

  const newTask = () => {
    const channelId = ensureChannelId();
    if (!channelId) return;
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "new_task_open",
      surface: "sidebar",
      channel_id: channelId,
    });
    openTaskInput({ channelId });
  };

  // The one row in the list that carries a glyph, and it earns the exception:
  // this is the space nobody else can see, and the lock is the only thing that
  // says so. Its name starts a glyph's width right of the others, which is the
  // cost of marking it.
  const glyph = channelGlyph(PERSONAL_CHANNEL_LABEL, {
    personal: true,
    size: 14,
    weight: isUnread ? "bold" : undefined,
    className: cn(
      "shrink-0",
      isUnread || isActive
        ? "text-foreground"
        : "text-muted-foreground group-hover/button:text-foreground",
    ),
  });

  return (
    <>
      <Box className="group/chan relative">
        <SpaceRowSurface
          asOption={spacesLayout}
          optionValue={meChannel?.id ?? PERSONAL_ROW_VALUE}
          data-selected={(isActive && !expanded) || undefined}
          onClick={openPersonalChannel}
          // Personal is a starred space among the others, so it takes the same
          // inset rather than sitting out at the heading's margin.
          className={spacesLayout ? "pl-2" : undefined}
        >
          {onToggleExpanded && meChannel && (
            <SpaceDisclosure
              expanded={expanded}
              spaceName={PERSONAL_CHANNEL_LABEL}
              onToggle={() => onToggleExpanded(meChannel.id)}
            />
          )}
          {glyph}
          <span
            className={cn(
              "truncate text-[13px]",
              isUnread ? "font-bold" : "font-medium",
              isUnread || isActive ? "text-foreground" : ROW_LABEL_TONE,
            )}
          >
            {PERSONAL_CHANNEL_LABEL}
          </span>
          <span className="mt-[2px] flex shrink-0 items-center gap-1">
            <SpaceAttentionDot
              count={blockedSessions}
              tone="blocked"
              faded={expanded}
            />
            <SpaceAttentionDot count={unreadSessions} faded={expanded} />
          </span>
          {hotkeySlot != null && (
            <Kbd className="!mr-0 ml-auto shrink-0 opacity-50 group-hover/chan:opacity-0">
              {formatHotkey(`mod+${hotkeySlot}`)}
            </Kbd>
          )}
        </SpaceRowSurface>
        <div className="absolute top-0 right-1">
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  variant="outline"
                  size="icon-xs"
                  aria-label={`New task in ${PERSONAL_CHANNEL_LABEL}`}
                  className="gap-1 opacity-0 transition-opacity group-hover:border-border group-hover/chan:opacity-100"
                  onClick={newTask}
                >
                  <PlusIcon size={12} weight="bold" />
                </Button>
              }
            />
            <TooltipContent side="top">New task</TooltipContent>
          </Tooltip>
        </div>
      </Box>
      {expanded && meChannel && (
        <SpaceTaskRows
          spaceId={meChannel.id}
          tasks={tasks ?? NO_TASKS}
          asOption={spacesLayout}
          onOpenSpace={openPersonalChannel}
        />
      )}
    </>
  );
});

// Collapse state is keyed per section in the shared sidebar store, so it
// persists across navigation and restarts. Prefixed to stay clear of the Code
// sidebar's folder sections, which key the same set by folder path.
const STARRED_SECTION_ID = "channels:starred";
const CHANNELS_SECTION_ID = "channels:all";

/** A heading's identity in the flat list, kept clear of any channel's id. */
const sectionValue = (sectionId: string) => `section:${sectionId}`;

// A collapsible sidebar group ("Starred" / "Channels"). Base UI directly rather
// than quill's Collapsible: quill styles its trigger as a button (which fought
// the label styling) and animates the panel height (which janked on a list this
// long). Unstyled parts give a plain label row that snaps.
//
// The whole header row is the trigger, and the label is all of it: the headings
// are few, named, and always in the same order, so a glyph beside each was
// decoration rather than a way of telling them apart.
function ChannelGroup({
  sectionId,
  label,
  className,
  flat,
  keepMounted = true,
  asOption = false,
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
  /**
   * Under the layout the heading is a row of the tree like any other: ↑/↓ walk
   * onto it, → opens the section, ← closes it. Off the layout there is no search
   * box driving a list, so it stays a plain label you click.
   */
  asOption?: boolean;
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
      className={cn(className, "mb-2")}
    >
      {/* MenuLabel carries the sidebar's label styling; `render` keeps it a
          real button so the whole row is clickable. Wrapped in an option when
          the keyboard walks the list, so the heading is a stop on the way down
          rather than a gap the highlight jumps over. */}
      <Collapsible.Trigger
        className={cn(
          "group/group-trigger flex w-full items-center gap-2 py-1",
          // quill wraps an option's children in its own flex row, so the caret's
          // `ml-auto` has nothing to push against until that row is full width.
          // The highlight is the rows' own hover fill rather than quill's focus
          // ring, for the reason SpaceRowSurface gives.
          asOption &&
            "rounded-sm ring-offset-0 data-highlighted:bg-fill-hover data-highlighted:ring-0 [&>span]:w-full [&>span]:items-center",
        )}
        render={
          asOption ? (
            <AutocompleteItem
              value={sectionValue(sectionId)}
              render={<MenuLabel render={<button type="button" />} />}
            />
          ) : (
            <MenuLabel render={<button type="button" />} />
          )
        }
      >
        {label}
        {/* On the right, because the heading's name is the left edge every row
            beneath it lines up to. Always drawn: which way the section is, is
            the one thing this row has to say. */}
        {isOpen ? (
          <CaretDownIcon size={12} className="shrink-0" />
        ) : (
          <CaretRightIcon size={12} className="shrink-0" />
        )}
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

// The channel list is the list pane of the sidebar slider. The personal channel
// is pinned at the top; starred channels surface in their own section
// so the ones you use most stay in reach; the rest sit under a "Channels"
// label. Creating anything goes through the floating ChannelsFab, mounted by
// the sidebar outside this scroll region.
export function ChannelsList() {
  const { channels: allChannels, isLoading } = useChannels();
  // ChannelHotkeys owns the keys these slots describe; sharing the derivation
  // keeps the advertised key and the key that fires in agreement — including
  // the fact that it only binds them under the layout, so off it the list
  // advertises nothing.
  const { slotFor } = useStarredChannelSlots();
  // Search and the shortcut hints belong to the slider, where this list is a
  // pane you switch channels from. The alpha still renders it as a plain tree.
  const channelsLayout = useChannelsLayout();

  const isUnread = useIsChannelUnread();
  const unreadSessions = useUnreadSessionCount();
  const blockedSessions = useBlockedSessionCount();

  const [query, setQuery] = useState("");
  const normalizedQuery = channelsLayout ? query.trim().toLowerCase() : "";
  const matches = (name: string) =>
    !normalizedQuery || name.toLowerCase().includes(normalizedQuery);

  // The personal channel renders as a pinned row, not a shared channel.
  const me = allChannels.find((c) => c.channelType === "personal");
  const channels = allChannels.filter((c) => c.channelType !== "personal");
  const starred = channels.filter((c) => c.starred);
  const others = channels.filter((c) => !c.starred);

  // Searching collapses the sections into one flat list: the group labels only
  // stand between you and the row you already named, and an empty "Starred"
  // heading reads as a result that isn't there.
  const searchResults = channels.filter((c) => matches(c.name));
  // Its old name too, so someone who still types "me" lands on it. A search
  // alias, not a second identity: nothing else matches on the old name.
  const meMatches =
    matches(PERSONAL_CHANNEL_LABEL) || matches(PERSONAL_CHANNEL_NAME);
  const noMatches =
    normalizedQuery !== "" && !meMatches && !searchResults.length;

  // The tree's expansion, and the tasks the expanded spaces show. Searching
  // flattens the list — a query is a request for the space you named, and rows
  // for tasks you didn't would sit between you and it.
  const expandedSpaceIds = useSpaceTreeStore((s) => s.expandedSpaceIds);
  const toggleSpace = useSpaceTreeStore((s) => s.toggleSpace);
  const expandSpace = useSpaceTreeStore((s) => s.expandSpace);
  const collapseSpace = useSpaceTreeStore((s) => s.collapseSpace);
  const setHighlightedValue = useSpaceTreeStore((s) => s.setHighlightedValue);
  const treeOn = !normalizedQuery;
  const isExpanded = (spaceId: string | undefined) =>
    treeOn && spaceId != null && expandedSpaceIds.has(spaceId);
  // One feed query per open space, and none for the rest. Sorted so the array
  // only changes when the set of open spaces does.
  const openSpaceIds = useMemo(
    () =>
      treeOn
        ? allChannels
            .map((channel) => channel.id)
            .filter((id) => expandedSpaceIds.has(id))
            .sort()
        : [],
    [allChannels, expandedSpaceIds, treeOn],
  );
  const tasksBySpace = useRecentSpaceTasks(openSpaceIds);
  // Pin / archive / command centre for every session row, built once here
  // rather than once per row.
  const spaceTaskActions = useSpaceTaskActions();
  const tasksOf = (spaceId: string | undefined): SpaceTasks =>
    (spaceId && tasksBySpace.get(spaceId)) || NO_TASKS;

  // The rows below, in render order, as the flat list the keyboard walks.
  // Autocomplete needs the values to map a highlight index onto — without it the
  // first ArrowDown after a keystroke is swallowed re-establishing the highlight
  // it already shows — and ArrowLeft needs to know which space a task hangs off.
  // A collapsed group or space renders no rows, so it contributes none.
  const collapsedSections = useSidebarStore((s) => s.collapsedSections);
  const toggleSection = useSidebarStore((s) => s.toggleSection);
  const meValue = me?.id ?? PERSONAL_ROW_VALUE;
  const starredValue = sectionValue(STARRED_SECTION_ID);
  const channelsValue = sectionValue(CHANNELS_SECTION_ID);
  const spaceNodes = (
    value: string,
    spaceId: string | undefined,
    parentValue?: string,
  ): SpaceTreeNode[] => {
    const space: SpaceTreeNode = { kind: "space", value, spaceId, parentValue };
    if (!isExpanded(spaceId) || !spaceId) return [space];
    const tasks = tasksOf(spaceId);
    return [
      space,
      ...tasks.items.map(
        (item): SpaceTreeNode => ({
          kind: "task",
          value: item.key,
          spaceId,
          parentValue: value,
        }),
      ),
      // "View all" is a leaf like any other, so ⏎ lands on it and ← from it
      // closes the space the way it does from a session.
      ...(hasViewAllRow(tasks)
        ? [
            {
              kind: "task" as const,
              value: viewAllValue(spaceId),
              spaceId,
              parentValue: value,
            },
          ]
        : []),
    ];
  };
  const nodes: SpaceTreeNode[] = normalizedQuery
    ? [
        ...(meMatches ? spaceNodes(meValue, me?.id) : []),
        ...searchResults.flatMap((channel) =>
          spaceNodes(channel.id, channel.id),
        ),
      ]
    : [
        // A heading is a row of the tree, so it is a node whether or not its
        // section is open — a folded section is still somewhere ↓ can land and
        // → can open.
        { kind: "section", value: starredValue, sectionId: STARRED_SECTION_ID },
        // Personal leads the starred section rather than floating above it. It is
        // the space you always keep, so it belongs with the ones you chose to
        // keep. Folding the section away takes it with them.
        ...(collapsedSections.has(STARRED_SECTION_ID)
          ? []
          : [
              ...spaceNodes(meValue, me?.id, starredValue),
              ...starred.flatMap((channel) =>
                spaceNodes(channel.id, channel.id, starredValue),
              ),
            ]),
        {
          kind: "section",
          value: channelsValue,
          sectionId: CHANNELS_SECTION_ID,
        },
        ...(collapsedSections.has(CHANNELS_SECTION_ID)
          ? []
          : others.flatMap((channel) =>
              spaceNodes(channel.id, channel.id, channelsValue),
            )),
      ];
  const optionValues = nodes.map((node) => node.value);

  // Coming back from a space, the list is what you came here to browse — so the
  // search box takes focus and any previous query is selected, ready to be typed
  // over. Only on the transition: a cold start rests on the channel pane, and
  // re-focusing on every render would steal focus from the rows themselves.
  const pane = useChannelPaneStore((s) => s.pane);
  const previousPane = useRef(pane);
  useEffect(() => {
    const cameFromChannel = previousPane.current === "channel";
    previousPane.current = pane;
    if (!channelsLayout || pane !== "list" || !cameFromChannel) return;
    requestSidebarSearchFocus();
  }, [pane, channelsLayout]);

  // Which row the keyboard is on. A ref rather than state: the arrow handlers
  // read it during the event, and re-rendering the whole list on every ↑/↓ is
  // exactly the cost this pane can't afford.
  const highlightedValue = useRef<string | undefined>(undefined);

  // ArrowRight opens a space (then steps into it); ArrowLeft closes the one
  // you're in and puts the highlight back on its space. Both defer to the text
  // caret first — the same box holds the query, so a key that would move the
  // caret through it belongs to the text.
  const onTreeKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    if (!treeOn) return;
    const input = event.currentTarget;
    const { selectionStart, selectionEnd, value } = input;
    const atStart = selectionStart === 0 && selectionEnd === 0;
    const atEnd =
      selectionStart === value.length && selectionEnd === value.length;
    const node = nodes.find((n) => n.value === highlightedValue.current);
    if (!node) return;

    if (event.key === "ArrowRight") {
      if (!atEnd) return;
      if (node.kind === "section") {
        event.preventDefault();
        if (collapsedSections.has(node.sectionId)) {
          toggleSection(node.sectionId);
          return;
        }
        moveHighlight(input, "ArrowDown", 1);
        return;
      }
      if (node.kind !== "space" || !node.spaceId) return;
      event.preventDefault();
      if (!expandedSpaceIds.has(node.spaceId)) {
        expandSpace(node.spaceId);
        return;
      }
      // Already open: the next press walks into it, so ArrowRight then ArrowDown
      // and ArrowRight twice land in the same place.
      moveHighlight(input, "ArrowDown", 1);
      return;
    }

    if (!atStart) return;
    // A heading has nothing above it to step to, so ← only ever folds it.
    if (node.kind === "section") {
      if (collapsedSections.has(node.sectionId)) return;
      event.preventDefault();
      toggleSection(node.sectionId);
      return;
    }
    if (node.kind === "task") {
      event.preventDefault();
      // Move first, while the children are still rendered — the highlight is an
      // index into the list, so walking up to the parent has to happen before
      // the rows between here and it stop existing.
      const steps =
        optionValues.indexOf(node.value) -
        optionValues.indexOf(node.parentValue);
      moveHighlight(input, "ArrowUp", steps);
      collapseSpace(node.spaceId);
      return;
    }
    if (node.spaceId && expandedSpaceIds.has(node.spaceId)) {
      event.preventDefault();
      collapseSpace(node.spaceId);
      return;
    }
    // Closed already, so ← does what it does from a session: steps up to the
    // row this one hangs off, which for a space is its heading.
    if (!node.parentValue) return;
    event.preventDefault();
    moveHighlight(
      input,
      "ArrowUp",
      optionValues.indexOf(node.value) - optionValues.indexOf(node.parentValue),
    );
  };

  const rows = normalizedQuery ? (
    <>
      {meMatches && <PersonalChannelRow />}
      {searchResults.map((channel) => (
        <ChannelSection
          key={channel.id}
          channel={channel}
          isUnread={isUnread(channel.id)}
          unreadSessions={unreadSessions(channel.id)}
          blockedSessions={blockedSessions(channel.id)}
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
      {/* Always rendered: personal lives here, so the section is never empty. */}
      <ChannelGroup
        sectionId={STARRED_SECTION_ID}
        label="Starred"
        flat={channelsLayout}
        keepMounted={!channelsLayout}
        asOption={channelsLayout}
      >
        <PersonalChannelRow
          hotkeySlot={channelsLayout && me ? slotFor(me) : undefined}
          expanded={isExpanded(me?.id)}
          tasks={tasksOf(me?.id)}
          onToggleExpanded={toggleSpace}
        />
        {starred.map((channel) => (
          <ChannelSection
            key={channel.id}
            channel={channel}
            isUnread={isUnread(channel.id)}
            unreadSessions={unreadSessions(channel.id)}
            blockedSessions={blockedSessions(channel.id)}
            hotkeySlot={channelsLayout ? slotFor(channel) : undefined}
            expanded={isExpanded(channel.id)}
            tasks={tasksOf(channel.id)}
            onToggleExpanded={toggleSpace}
          />
        ))}
      </ChannelGroup>

      <ChannelGroup
        sectionId={CHANNELS_SECTION_ID}
        label={channelsLayout ? "Spaces" : "Channels"}
        flat={channelsLayout}
        keepMounted={!channelsLayout}
        asOption={channelsLayout}
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
            isUnread={isUnread(channel.id)}
            unreadSessions={unreadSessions(channel.id)}
            blockedSessions={blockedSessions(channel.id)}
            expanded={isExpanded(channel.id)}
            tasks={tasksOf(channel.id)}
            onToggleExpanded={toggleSpace}
          />
        ))}
      </ChannelGroup>
    </>
  );

  // Bottom padding clears the floating create button (ChannelsFab), so the last
  // channel stays reachable at full scroll.
  const scrollClass =
    "scroll-mask-8 min-h-0 flex-1 overflow-y-auto px-2 pt-2 pb-16";
  // quill sizes its list as a popup — a ~250px cap and its own 4px padding —
  // and ships it unlayered, so plain utilities lose to it however they're
  // ordered. Here the list *is* the pane, so the cap has to go and the pane's
  // own padding has to win: `!` is what outranks an unlayered rule.
  const listClass = cn(
    "flex flex-col gap-px",
    "!max-h-none !px-2 !pt-2 !pb-16 scroll-py-8",
    scrollClass,
  );

  const body = (
    <Flex direction="column" className="h-full min-h-0">
      {channelsLayout && (
        <SidebarSearchHeader
          title="Spaces"
          query={query}
          placeholder="Search spaces…"
          searchLabel="Search spaces"
          onClear={() => setQuery("")}
          onKeyDown={onTreeKeyDown}
        />
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
      <SpaceTaskActionsProvider value={spaceTaskActions}>
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
            // ArrowRight / ArrowLeft act on the row the keyboard is on, and this
            // is the only way to know which one that is.
            onItemHighlighted={(value, eventDetails) => {
              highlightedValue.current = value;
              // The store copy is what opens a session's card under the
              // keyboard; the ref stays because the arrow handlers read the
              // highlight during the event, before any render has happened.
              // Only a keyboard highlight is stored: a pointer one is the row's
              // own hover, and `keepHighlight` keeps it set after the pointer
              // has left the list, which would strand that card open.
              setHighlightedValue(
                eventDetails.reason === "keyboard" ? value : undefined,
              );
            }}
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
      </SpaceTaskActionsProvider>
    </TooltipProvider>
  );
}
