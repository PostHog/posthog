import {
  ArchiveIcon,
  CaretRightIcon,
  DotsThreeIcon,
  FolderSimpleIcon,
  PencilSimpleIcon,
  PushPinIcon,
  PushPinSlashIcon,
  SquaresFourIcon,
  StopCircle,
  TrashIcon,
} from "@phosphor-icons/react";
import { sessionsLabel } from "@posthog/core/sidebar/selection";
import {
  Button,
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSub,
  ContextMenuSubTrigger,
  ContextMenuTrigger,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useFileTaskToChannel } from "@posthog/ui/features/canvas/hooks/useFileTaskToChannel";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import type { SidebarBulkActions } from "@posthog/ui/features/sidebar/useSidebarBulkActions";
import {
  type MenuFlyoutItem,
  MenuSubFlyout,
  SearchableMenuFlyout,
} from "@posthog/ui/primitives/SearchableMenuFlyout";
import { type ComponentType, type ReactNode, useMemo, useState } from "react";

/**
 * What a row's menu can do. The row owns the handlers because they're the same
 * ones its list already has (pin, archive, delete, rename inline); only filing —
 * which needs the channel list and a mutation — belongs to the menu.
 *
 * Canvases share this menu but not all of it: they can be pinned and deleted,
 * and they can't be filed to a space or given a command-centre cell, both of
 * which are task-shaped. `kind` is what decides, so a canvas gets a menu of the
 * actions it has rather than a full one with half its items dead.
 */
export interface TaskRowMenuProps {
  kind: "task" | "canvas";
  id: string;
  title: string;
  isPinned: boolean;
  /** The channel this task is already filed to, ticked in "File to…". */
  channelId?: string;
  /** Absent when the command centre is full, which disables the item. */
  onAddToCommandCenter?: () => void;
  /** Absent where there's no inline rename to open — canvases, for now. */
  onRename?: () => void;
  onStop?: () => void;
  onTogglePin: () => void;
  /** Tasks are archived; canvases are deleted (with an undo window). */
  onArchive?: () => void;
  onDelete?: () => void;
}

// The two menus differ only in which primitives draw them, so the item list is
// written once against this shape. Base UI builds context menus on the same Menu
// parts as dropdowns, so the props line up; typing them structurally keeps the
// shared content from having to know which surface it's on.
interface MenuParts {
  Item: ComponentType<{
    children: ReactNode;
    disabled?: boolean;
    variant?: "default" | "destructive";
    onClick?: () => void;
  }>;
  Sub: ComponentType<{ children: ReactNode }>;
  SubTrigger: ComponentType<{ children: ReactNode }>;
}

const CONTEXT_PARTS: MenuParts = {
  Item: ContextMenuItem,
  Sub: ContextMenuSub,
  SubTrigger: ContextMenuSubTrigger,
};

const DROPDOWN_PARTS: MenuParts = {
  Item: DropdownMenuItem,
  Sub: DropdownMenuSub,
  SubTrigger: DropdownMenuSubTrigger,
};

/**
 * The row's actions, in the order the native menu used: the edits, then the
 * places a task can be sent, then the destructive one last.
 */
function TaskRowMenuItems({
  parts,
  menu,
}: {
  parts: MenuParts;
  menu: TaskRowMenuProps;
}) {
  const { Item, Sub, SubTrigger } = parts;
  // "File to…" is a Project Bluebird feature; gate the channel fetch behind the
  // flag so neither the submenu nor its request reaches ungated users.
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  const isTask = menu.kind === "task";
  const { channels } = useChannels({ enabled: bluebirdEnabled && isTask });
  const fileToChannel = useFileTaskToChannel();

  const channelItems: MenuFlyoutItem[] = channels.map((channel) => ({
    id: channel.id,
    label: channel.name,
    current: channel.id === menu.channelId,
    starred: channel.starred,
  }));

  return (
    <>
      <Item onClick={menu.onTogglePin}>
        {menu.isPinned ? (
          <PushPinSlashIcon size={14} />
        ) : (
          <PushPinIcon size={14} />
        )}
        {menu.isPinned ? "Unpin" : "Pin"}
      </Item>
      {menu.onRename && (
        <Item onClick={menu.onRename}>
          <PencilSimpleIcon size={14} />
          Rename
        </Item>
      )}
      {menu.onStop && (
        <Item onClick={menu.onStop}>
          <StopCircle size={14} />
          Stop task
        </Item>
      )}
      {isTask && (
        <Item
          disabled={!menu.onAddToCommandCenter}
          onClick={menu.onAddToCommandCenter}
        >
          <SquaresFourIcon size={14} />
          Add to Command Center
        </Item>
      )}
      {isTask && channelItems.length > 0 && (
        <Sub>
          <SubTrigger>
            <FolderSimpleIcon size={14} />
            File to…
          </SubTrigger>
          <MenuSubFlyout className="w-64 p-0">
            <SearchableMenuFlyout
              items={channelItems}
              placeholder="Search spaces…"
              emptyLabel="No spaces"
              onSelect={(channelId) =>
                fileToChannel(channelId, menu.id, menu.title)
              }
            />
          </MenuSubFlyout>
        </Sub>
      )}
      {menu.onArchive && (
        <Item onClick={menu.onArchive}>
          <ArchiveIcon size={14} />
          Archive
        </Item>
      )}
      {/* The ellipsis is the promise that a confirm follows — deleting a canvas
          takes it away from everyone in the space. */}
      {menu.onDelete && (
        <Item variant="destructive" onClick={menu.onDelete}>
          <TrashIcon size={14} />
          Delete…
        </Item>
      )}
    </>
  );
}

/**
 * What a right-click does when the row it landed on is part of a selection: the
 * same four actions the selection bar offers, so the two paths can't drift.
 * Archiving asks first, and the caller owns that confirm because it outlives
 * the menu.
 */
export interface TaskRowBulkMenu {
  actions: SidebarBulkActions;
  onArchive: () => void;
}

function TaskRowBulkMenuItems({
  parts,
  bulk,
}: {
  parts: MenuParts;
  bulk: TaskRowBulkMenu;
}) {
  const { Item, Sub, SubTrigger } = parts;
  const { actions } = bulk;
  const sessions = sessionsLabel(actions.selectedCount);
  // No tick: a batch can span spaces, so there is no one channel to mark.
  const channelItems: MenuFlyoutItem[] = actions.channels.map((channel) => ({
    id: channel.id,
    label: channel.name,
    current: false,
    starred: channel.starred,
  }));

  return (
    <>
      <Item disabled={actions.isPinning} onClick={actions.pinSelected}>
        {actions.pinDirection === "pin" ? (
          <PushPinIcon size={14} />
        ) : (
          <PushPinSlashIcon size={14} />
        )}
        {actions.pinLabel}
      </Item>
      <Item onClick={actions.addSelectedToCommandCenter}>
        <SquaresFourIcon size={14} />
        Add {sessions} to Command Center
      </Item>
      {channelItems.length > 0 && (
        <Sub>
          <SubTrigger>
            <FolderSimpleIcon size={14} />
            File {sessions} to…
          </SubTrigger>
          <MenuSubFlyout className="w-64 p-0">
            <SearchableMenuFlyout
              items={channelItems}
              placeholder="Search spaces…"
              emptyLabel="No spaces"
              onSelect={(channelId) => void actions.fileSelectedTo(channelId)}
            />
          </MenuSubFlyout>
        </Sub>
      )}
      {/* The ellipsis is the promise that a confirm follows: a bulk archive has
          no undo toast behind it. */}
      <Item
        variant="destructive"
        disabled={actions.isArchiving}
        onClick={bulk.onArchive}
      >
        <ArchiveIcon size={14} />
        Archive {sessions}…
      </Item>
    </>
  );
}

/**
 * The same actions as a plain list, for a surface that is already open — the
 * row's hover card. Rows are quill buttons rather than menu items because
 * nothing here is a popup: there's no menu root to give `DropdownMenuItem` its
 * keyboard handling, and a button is what quill offers for a click target in a
 * card.
 *
 * `onAction` closes the surface once something has been chosen, and
 * `onSubmenuOpenChange` reports the one thing that *is* a popup ("File to…"), so
 * a hover surface can stay open while the pointer is inside it.
 */
export function TaskRowDropdownMenu({ menu }: { menu: TaskRowMenuProps }) {
  const [open, setOpen] = useState(false);

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger
        render={
          <Button
            variant="default"
            size="icon-xs"
            aria-label={`Options for ${menu.title || "task"}`}
            onClick={(event) => event.stopPropagation()}
          />
        }
      >
        <DotsThreeIcon size={14} weight="bold" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <TaskRowMenuItems parts={DROPDOWN_PARTS} menu={menu} />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function TaskRowMenuList({
  menu,
  onAction,
  onSubmenuOpenChange,
}: {
  menu: TaskRowMenuProps;
  onAction: () => void;
  onSubmenuOpenChange: (open: boolean) => void;
}) {
  const parts: MenuParts = useMemo(
    () => ({
      Item: ({ children, disabled, variant, onClick }) => (
        <Button
          variant={variant === "destructive" ? "destructive" : "default"}
          left
          disabled={disabled}
          className="w-full"
          onClick={() => {
            onClick?.();
            onAction();
          }}
        >
          {children}
        </Button>
      ),
      Sub: ({ children }) => (
        <DropdownMenu onOpenChange={onSubmenuOpenChange}>
          {children}
        </DropdownMenu>
      ),
      // `openOnHover`, so the spaces flyout arrives the way a submenu does in
      // the right-click menu — pointing at the row is the whole gesture, and
      // this card is a hover surface to begin with.
      SubTrigger: ({ children }) => (
        <DropdownMenuTrigger
          openOnHover
          delay={150}
          closeDelay={100}
          render={
            <Button variant="default" left className="w-full">
              <span className="flex flex-1 items-center gap-2 text-left">
                {children}
              </span>
              <CaretRightIcon size={12} />
            </Button>
          }
        />
      ),
    }),
    [onAction, onSubmenuOpenChange],
  );

  return (
    <div className="flex flex-col">
      <TaskRowMenuItems parts={parts} menu={menu} />
    </div>
  );
}

/**
 * The same menu on right-click, wrapping the row. A row inside a multi-session
 * selection gets the selection's menu instead of its own: acting on one row
 * while four are highlighted is the surprise this avoids.
 */
export function TaskRowContextMenu({
  menu,
  bulk,
  onOpenChange,
  children,
}: {
  menu: TaskRowMenuProps;
  bulk?: TaskRowBulkMenu | null;
  onOpenChange?: (open: boolean) => void;
  children: ReactNode;
}) {
  return (
    <ContextMenu onOpenChange={onOpenChange}>
      <ContextMenuTrigger render={<div className="min-w-0" />}>
        {children}
      </ContextMenuTrigger>
      {/* Wider for a batch: its labels carry a count and a noun ("Add 6
          sessions to Command Center"), which the row's own labels don't. */}
      <ContextMenuContent className={bulk ? "w-72" : "w-56"}>
        {bulk ? (
          <TaskRowBulkMenuItems parts={CONTEXT_PARTS} bulk={bulk} />
        ) : (
          <TaskRowMenuItems parts={CONTEXT_PARTS} menu={menu} />
        )}
      </ContextMenuContent>
    </ContextMenu>
  );
}
