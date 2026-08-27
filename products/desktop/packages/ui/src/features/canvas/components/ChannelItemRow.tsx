import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Avatar,
  AvatarFallback,
  AvatarGroup,
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { writeCanvasDragData } from "@posthog/ui/features/canvas/canvasDrag";
import { ChannelItemHoverCard } from "@posthog/ui/features/canvas/components/ChannelItemHoverCard";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import {
  type TaskRowBulkMenu,
  TaskRowContextMenu,
  type TaskRowMenuProps,
} from "@posthog/ui/features/canvas/components/TaskRowMenu";
import { useChannelItemMetadata } from "@posthog/ui/features/canvas/hooks/useChannelItemFacts";
import { useChannelTaskStatus } from "@posthog/ui/features/canvas/hooks/useChannelTaskStatus";
import { useIsCanvasPendingDelete } from "@posthog/ui/features/canvas/stores/pendingCanvasDeleteStore";
import { InlineEditInput } from "@posthog/ui/features/sidebar/components/items/TaskItem";
import {
  PinnedBadge,
  TaskBadgeStack,
  TaskStatusDot,
  TaskStatusTooltips,
} from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import type { TaskStatusInput } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import {
  type TaskDot,
  taskDot,
} from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import { writeTaskDragData } from "@posthog/ui/features/sidebar/taskDrag";
import { SESSION_ROW_ATTRIBUTE } from "@posthog/ui/features/sidebar/useMarqueeSelection";
import { HandoffTaskDialog } from "@posthog/ui/features/task-detail/components/HandoffTaskDialog";
import {
  type DragEvent,
  type ReactNode,
  useCallback,
  useMemo,
  useState,
} from "react";

/**
 * What a row can do. One object per channel rather than closures per item, so
 * the item list stays plain data and doesn't rebuild on every navigation.
 */
export interface ChannelItemActions {
  open: (item: ChannelItemModel) => void;
  togglePin: (item: ChannelItemModel) => void;
  /** Pins or unpins a whole batch, which a drag over the pinned run applies. */
  setPinned: (items: ChannelItemModel[], pinned: boolean) => void;
  archive: (item: ChannelItemModel) => void;
  /** Canvases only — a task is archived, not deleted. */
  remove: (item: ChannelItemModel) => void;
  fileCanvas: (item: ChannelItemModel, channelId: string) => void;
}

// The channel sidebar's own chrome. Deliberately not shared with the Code
// sidebar's TaskItem: that one is still on the absolute gray scale, while these
// rows use the theme's fill/foreground tokens.
const TIMESTAMP_CLASS = "shrink-0 text-[11px] text-muted-foreground";
// The badges own the trailing slot outright now that the actions have moved to
// the hover card — a row's identity is what you scan a task list for. The gap is
// between stacks (a pin, then the status badges), not within one.
const TRAILING_CLASS = "flex shrink-0 items-center gap-1";

/**
 * A canvas waiting out its delete-undo window. Red and flashing because it is
 * the one row state that is about to stop existing — everything else in this
 * vocabulary is something you can come back to.
 */
const DELETING_DOT: TaskDot = {
  tone: "red",
  style: "solid",
  pulse: true,
  label: "Deleting…",
};

/**
 * One badge in a row's trailing stack, named on hover like the ones
 * `TaskBadgeStack` draws — the row's tooltip provider is already up, so this
 * shares its open delay.
 */
function RowBadge({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Tooltip disableHoverablePopup>
      {/* `cursor-default`: a badge names a fact about the row, it isn't a
          control — see the same note in TaskBadgeStack. */}
      <TooltipTrigger
        render={
          <Avatar
            size="xs"
            aria-label={label}
            role="img"
            className="cursor-default"
          >
            <AvatarFallback className="bg-transparent">
              {children}
            </AvatarFallback>
          </Avatar>
        }
      />
      <TooltipContent side="top" className="pointer-events-none select-none">
        {label}
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * A canvas's trailing stack: the pin, then its template glyph. Same stack as a
 * task's badges — a pinned canvas reads the way a pinned task does.
 */
function CanvasBadgeStack({
  item,
  pinned,
}: {
  item: ChannelItemModel;
  pinned?: boolean;
}) {
  return (
    <AvatarGroup stacked reverse size="xs" className="shrink-0">
      {pinned ? <PinnedBadge /> : null}
      <RowBadge label="Canvas">
        {/* Violet is the canvas colour everywhere else it appears — the
            artifacts list, the thread panel, the pinned menu — so the badge says
            "canvas" the same way they do. */}
        {iconForTemplate(item.templateId ?? "freeform", {
          size: 9,
          className: "text-violet-9",
        })}
      </RowBadge>
    </AvatarGroup>
  );
}

/**
 * A row's leading mark, always the task-list state vocabulary. Canvases have no
 * live run, so they take the quiet dot and move their glyph to the trailing
 * stack. Deleting is the exception: that one a canvas row has to shout.
 */
function ChannelItemDot({
  item,
  status,
}: {
  item: ChannelItemModel;
  status: TaskStatusInput | null;
}) {
  const pendingDelete = useIsCanvasPendingDelete(item.id);
  const deleting = item.kind === "canvas" && pendingDelete;
  return (
    <TaskStatusDot dot={deleting ? DELETING_DOT : taskDot(status ?? {})} />
  );
}

/**
 * What a row looks like, with nothing behind it, so the drag preview can draw
 * one without wiring it. Rendering `ChannelItemRow` for that opened a second PR
 * lookup per drag, plus a hover card and a context menu nothing could reach.
 *
 * Takes `status` rather than resolving it: how much is worth resolving is the
 * caller's call, see `useChannelTaskStatus`.
 */
export function ChannelItemRowView({
  item,
  status,
  subtitle,
  isActive,
  isSelected = false,
  showPinBadge = true,
  draggable = false,
  onClick,
  onDragStart,
  onDragEnd,
}: {
  item: ChannelItemModel;
  status: TaskStatusInput | null;
  /** The metadata row under the title, when the appearance settings ask for one. */
  subtitle?: ReactNode;
  isActive: boolean;
  isSelected?: boolean;
  showPinBadge?: boolean;
  draggable?: boolean;
  onClick?: (e: React.MouseEvent) => void;
  onDragStart?: (e: DragEvent) => void;
  onDragEnd?: (e: DragEvent) => void;
}) {
  const pinBadge = item.pinned && showPinBadge;
  return (
    <SidebarItem
      // The space's lists follow web conventions — every clickable row shows a
      // pointer, like the feed and activity rows — unlike the Code sidebar,
      // which keeps SidebarItem's native cursor-default.
      className="cursor-pointer"
      depth={0}
      icon={<ChannelItemDot item={item} status={status} />}
      // A non-string label opts out of SidebarItem's truncation tooltip.
      label={<span>{item.title}</span>}
      subtitle={subtitle}
      isActive={isActive}
      isSelected={isSelected}
      // Lets a drag-selection find the row and its session; canvases are not
      // selectable, so they stay unmarked and the marquee passes over them.
      {...(item.kind === "task" ? { [SESSION_ROW_ATTRIBUTE]: item.id } : {})}
      draggable={draggable}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onClick}
      endContent={
        <span className={TRAILING_CLASS}>
          {/* Badges take the timestamp's slot: identity (pin, source, cloud,
              PR) is what you scan a task list for, and the age is still on the
              preview card. */}
          {status ? (
            <TaskBadgeStack status={status} pinned={pinBadge} />
          ) : item.kind === "canvas" ? (
            <CanvasBadgeStack item={item} pinned={pinBadge} />
          ) : (
            <>
              {pinBadge && (
                <AvatarGroup stacked reverse size="xs" className="shrink-0">
                  <PinnedBadge />
                </AvatarGroup>
              )}
              <span className={TIMESTAMP_CLASS}>
                {formatRelativeTimeShort(item.ts)}
              </span>
            </>
          )}
        </span>
      }
    />
  );
}

export function ChannelItemRow({
  item,
  channelId,
  isActive,
  isSelected = false,
  actions,
  isEditing = false,
  onClick,
  showPinBadge = true,
  onRename,
  onAddToCommandCenter,
  onEditSubmit,
  onEditCancel,
  onDragStart,
  onDragEnd,
  bulk,
  onContextMenuOpenChange,
}: {
  item: ChannelItemModel;
  /** The space this row is listed under, ticked in the menu's "File to…". */
  channelId?: string;
  isActive: boolean;
  /** Part of a multi-session selection, so the row shows as picked. */
  isSelected?: boolean;
  actions: ChannelItemActions;
  isEditing?: boolean;
  /** Takes over the row's click, e.g. to modifier-click a selection. Falls back to opening it. */
  onClick?: (e: React.MouseEvent) => void;
  /** False under a "Pinned" header, which says it for every row beneath it. */
  showPinBadge?: boolean;
  /** Puts the row into inline-rename mode. Absent for canvases. */
  onRename?: () => void;
  /** Absent when the command centre has no free cell, which disables the item. */
  onAddToCommandCenter?: () => void;
  onEditSubmit?: (newTitle: string) => void;
  onEditCancel?: () => void;
  /** Only the space sidebar passes these; they drive its pin/unpin drag. */
  onDragStart?: (e: DragEvent) => void;
  onDragEnd?: (e: DragEvent) => void;
  /**
   * Present when this row is inside a multi-session selection, which its
   * right-click menu then acts on instead of the row alone. The confirm behind
   * `onArchive` belongs to the list, which owns the selection.
   */
  bulk?: TaskRowBulkMenu | null;
  onContextMenuOpenChange?: (open: boolean) => void;
}) {
  const status = useChannelTaskStatus(item);
  const subtitle = useChannelItemMetadata(item);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [handoffOpen, setHandoffOpen] = useState(false);
  const currentUser = useCurrentUser();
  const canHandoff =
    item.kind === "task" &&
    item.task != null &&
    item.authorUser?.id != null &&
    currentUser.data?.id === item.authorUser.id;
  const canFileCanvas =
    item.kind === "canvas" &&
    item.authorUuid != null &&
    currentUser.data?.uuid === item.authorUuid;
  const handleDragStart = useCallback(
    (event: DragEvent) => {
      if (item.kind === "canvas") {
        writeCanvasDragData(event.dataTransfer, item.id);
        event.dataTransfer.effectAllowed = "copy";
        return;
      }

      writeTaskDragData(event.dataTransfer, item.id);
      // Both, always. Command Center tiles ask for `copy` and the pinned run
      // asks for `move`; a source that permits only one resolves the other
      // pairing to no drop, and the tile silently stops accepting the row.
      event.dataTransfer.effectAllowed = "copyMove";
      onDragStart?.(event);
    },
    [item.id, item.kind, onDragStart],
  );

  // A canvas gets the same menu with the items it actually has: command-centre
  // placement, pin, filing, and delete instead of archive.
  //
  // Memoized because it travels to the shared preview card as the trigger's
  // payload, which is written to the card's store whenever its identity changes.
  const menu: TaskRowMenuProps = useMemo(
    () =>
      item.kind === "canvas"
        ? {
            kind: "canvas",
            id: item.id,
            title: item.title,
            isPinned: item.pinned,
            channelId,
            ...(canFileCanvas
              ? {
                  onFile: (targetChannelId: string) =>
                    actions.fileCanvas(item, targetChannelId),
                }
              : {}),
            onTogglePin: () => actions.togglePin(item),
            onAddToCommandCenter,
            // Confirm first, like the canvas menus in the artifacts grid and
            // the canvas header: the canvas and its history go for everyone.
            onDelete: () => setConfirmDeleteOpen(true),
          }
        : {
            kind: "task",
            id: item.id,
            title: item.title,
            isPinned: item.pinned,
            task: item.task ?? undefined,
            channelId,
            onAddToCommandCenter,
            onRename,
            onTogglePin: () => actions.togglePin(item),
            onArchive: () => actions.archive(item),
            ...(canHandoff ? { onHandoff: () => setHandoffOpen(true) } : {}),
          },
    // Ownership rides on the currentUser query, so these belong in deps for a
    // sign-in refresh to re-evaluate.
    [
      item,
      channelId,
      actions,
      onAddToCommandCenter,
      onRename,
      canHandoff,
      canFileCanvas,
    ],
  );

  if (isEditing) {
    return (
      <InlineEditInput
        depth={0}
        icon={<ChannelItemDot item={item} status={status} />}
        label={item.title}
        isActive={isActive}
        onSubmit={(newTitle) => onEditSubmit?.(newTitle)}
        onCancel={() => onEditCancel?.()}
      />
    );
  }

  // One tooltip provider per task row, shared by its dot and badges so moving
  // between them doesn't re-wait the open delay. Canvas rows have neither.
  const row = (
    <ChannelItemHoverCard item={item} menu={menu}>
      <ChannelItemRowView
        item={item}
        status={status}
        subtitle={subtitle}
        isActive={isActive}
        isSelected={isSelected}
        showPinBadge={showPinBadge}
        draggable
        onDragStart={handleDragStart}
        onDragEnd={onDragEnd}
        onClick={(e) => (onClick ? onClick(e) : actions.open(item))}
      />
    </ChannelItemHoverCard>
  );

  const tipped = <TaskStatusTooltips>{row}</TaskStatusTooltips>;
  // Right-click opens the same actions the hover card lists, from the same
  // definition, so the two can't drift.
  return (
    <>
      <TaskRowContextMenu
        menu={menu}
        bulk={bulk}
        onOpenChange={onContextMenuOpenChange}
      >
        {tipped}
      </TaskRowContextMenu>
      {/* The same confirm the artifacts grid and the canvas header show: a
          canvas goes for everyone in the space, so it isn't a one-click action
          however small the row is. The undo window still follows. */}
      <AlertDialog open={confirmDeleteOpen} onOpenChange={setConfirmDeleteOpen}>
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>Delete canvas</AlertDialogTitle>
            <AlertDialogDescription>
              Delete <span className="font-medium">{item.title}</span>? Its code
              and version history go for everyone in the space. You get a few
              seconds to undo, then it's permanent.
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
              onClick={() => {
                setConfirmDeleteOpen(false);
                actions.remove(item);
              }}
            >
              Delete
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {canHandoff && item.task ? (
        <HandoffTaskDialog
          task={item.task}
          open={handoffOpen}
          onOpenChange={setHandoffOpen}
        />
      ) : null}
    </>
  );
}
