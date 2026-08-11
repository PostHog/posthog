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
import { ChannelItemHoverCard } from "@posthog/ui/features/canvas/components/ChannelItemHoverCard";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import {
  TaskRowContextMenu,
  type TaskRowMenuProps,
} from "@posthog/ui/features/canvas/components/TaskRowMenu";
import { useChannelTaskStatus } from "@posthog/ui/features/canvas/hooks/useChannelTaskStatus";
import { useIsCanvasPendingDelete } from "@posthog/ui/features/canvas/stores/pendingCanvasDeleteStore";
import { InlineEditInput } from "@posthog/ui/features/sidebar/components/items/TaskItem";
import {
  PinnedBadge,
  TaskBadgeStack,
  TaskStatusDot,
  TaskStatusTooltips,
} from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import {
  type TaskDot,
  taskDot,
} from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import { type DragEvent, type ReactNode, useCallback, useState } from "react";

/**
 * What a row can do. One object per channel rather than closures per item, so
 * the item list stays plain data and doesn't rebuild on every navigation.
 */
export interface ChannelItemActions {
  open: (item: ChannelItemModel) => void;
  togglePin: (item: ChannelItemModel) => void;
  archive: (item: ChannelItemModel) => void;
  /** Canvases only — a task is archived, not deleted. */
  remove: (item: ChannelItemModel) => void;
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

export function ChannelItemRow({
  item,
  channelId,
  isActive,
  actions,
  isEditing = false,
  onRename,
  onAddToCommandCenter,
  onEditSubmit,
  onEditCancel,
}: {
  item: ChannelItemModel;
  /** The space this row is listed under, ticked in the menu's "File to…". */
  channelId?: string;
  isActive: boolean;
  actions: ChannelItemActions;
  isEditing?: boolean;
  /** Puts the row into inline-rename mode. Absent for canvases. */
  onRename?: () => void;
  /** Absent when the command centre has no free cell, which disables the item. */
  onAddToCommandCenter?: () => void;
  onEditSubmit?: (newTitle: string) => void;
  onEditCancel?: () => void;
}) {
  const status = useChannelTaskStatus(item);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  // A canvas inside its undo window stays in the list rather than vanishing and
  // reappearing on Undo, so the row has to say what's happening to it.
  const pendingDelete = useIsCanvasPendingDelete(item.id);
  const deleting = item.kind === "canvas" && pendingDelete;
  const handleDragStart = useCallback(
    (event: DragEvent) => {
      if (item.kind !== "task") return;

      event.dataTransfer.setData("text/x-task-id", item.id);
      event.dataTransfer.effectAllowed = "copy";
    },
    [item.id, item.kind],
  );
  // The row's leading mark is always the task-list state vocabulary. Canvases
  // have no live run, so they use the quiet dot and move their glyph to the
  // right-side identity stack — except while one is being deleted, which is the
  // one thing a canvas row has to shout.
  const rowIcon = (
    <TaskStatusDot dot={deleting ? DELETING_DOT : taskDot(status ?? {})} />
  );
  // A canvas gets the same menu with the items it actually has: pin, and delete
  // instead of archive. Filing and command-centre cells are task-shaped, and the
  // menu drops them rather than showing them dead.
  const menu: TaskRowMenuProps =
    item.kind === "canvas"
      ? {
          kind: "canvas",
          id: item.id,
          title: item.title,
          isPinned: item.pinned,
          onTogglePin: () => actions.togglePin(item),
          // Confirm first, like the canvas menus in the artifacts grid and the
          // canvas header: the canvas and its history go for everyone.
          onDelete: () => setConfirmDeleteOpen(true),
        }
      : {
          kind: "task",
          id: item.id,
          title: item.title,
          isPinned: item.pinned,
          channelId,
          onAddToCommandCenter,
          onRename,
          onTogglePin: () => actions.togglePin(item),
          onArchive: () => actions.archive(item),
        };

  if (isEditing) {
    return (
      <InlineEditInput
        depth={0}
        icon={rowIcon}
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
      <SidebarItem
        depth={0}
        icon={rowIcon}
        // A non-string label opts out of SidebarItem's truncation tooltip.
        label={<span>{item.title}</span>}
        isActive={isActive}
        draggable={item.kind === "task"}
        onDragStart={handleDragStart}
        onClick={() => actions.open(item)}
        endContent={
          <span className={TRAILING_CLASS}>
            {/* Badges take the timestamp's slot on a task row: the row's
                      identity (pin, source, cloud, PR) is what you scan a task
                      list for, and the relative age is still in the preview
                      card. The pin joins whichever stack the row has, rather
                      than standing beside it as a badge of its own. */}
            {status ? (
              <TaskBadgeStack status={status} pinned={item.pinned} />
            ) : item.kind === "canvas" ? (
              <CanvasBadgeStack item={item} pinned={item.pinned} />
            ) : (
              <>
                {item.pinned && (
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
    </ChannelItemHoverCard>
  );

  const tipped = <TaskStatusTooltips>{row}</TaskStatusTooltips>;
  // Right-click opens the same actions the hover card lists, from the same
  // definition, so the two can't drift.
  return (
    <>
      <TaskRowContextMenu menu={menu}>{tipped}</TaskRowContextMenu>
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
    </>
  );
}
