import {
  ArchiveIcon,
  CaretRightIcon,
  DotsThreeIcon,
  FolderSimpleIcon,
  MagnifyingGlassIcon,
  PencilSimpleIcon,
  PushPinIcon,
  PushPinSlashIcon,
  SquaresFourIcon,
  StopCircle,
  TrashIcon,
  UserSwitchIcon,
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
import type { Task } from "@posthog/shared/domain-types";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useFileTaskToChannel } from "@posthog/ui/features/canvas/hooks/useFileTaskToChannel";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useSidebarPeekStore } from "@posthog/ui/features/sidebar/sidebarPeekStore";
import { useHoldSidebarPeek } from "@posthog/ui/features/sidebar/useHoldSidebarPeek";
import type { SidebarBulkActions } from "@posthog/ui/features/sidebar/useSidebarBulkActions";
import { useTaskAnalysis } from "@posthog/ui/features/task-detail/components/TaskAnalysisButton";
import {
  type MenuFlyoutItem,
  MenuSubFlyout,
  SearchableMenuFlyout,
} from "@posthog/ui/primitives/SearchableMenuFlyout";
import {
  type ComponentType,
  type ReactElement,
  type ReactNode,
  useCallback,
  useMemo,
  useState,
} from "react";

/**
 * What a row's menu can do. The row owns the handlers because they're the same
 * ones its list already has (pin, archive, delete, rename inline); only filing —
 * which needs the channel list and a mutation — belongs to the menu.
 *
 * Canvases share this menu but not all of it: they can be added to the command
 * centre, pinned, filed, and deleted. `kind` decides which remaining actions
 * apply.
 */
export interface TaskRowMenuProps {
  kind: "task" | "canvas";
  id: string;
  title: string;
  isPinned: boolean;
  task?: Task;
  /** The channel this item is already filed to, ticked in "File to…". */
  channelId?: string;
  /** Absent when the command centre is full, which disables the item. */
  onAddToCommandCenter?: () => void;
  /** Absent where there's no inline rename to open — canvases, for now. */
  onRename?: () => void;
  onStop?: () => void;
  onTogglePin: () => void;
  /** Canvases supply their own filing mutation; task filing is shared here. */
  onFile?: (channelId: string) => void;
  /** Tasks are archived; canvases are deleted (with an undo window). */
  onArchive?: () => void;
  onDelete?: () => void;
  /** Owner-only: handing a task to a colleague needs a confirm dialog. */
  onHandoff?: () => void;
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

function TaskAnalysisMenuItem({
  Item,
  task,
}: {
  Item: MenuParts["Item"];
  task: Task;
}): ReactElement | null {
  const { canAnalyze, isPending, run } = useTaskAnalysis(task);
  if (!canAnalyze) return null;

  return (
    <Item disabled={isPending} onClick={run}>
      <MagnifyingGlassIcon size={14} />
      {isPending ? "Analyzing…" : "Run analysis"}
    </Item>
  );
}

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
  const analysisTask = isTask && menu.task?.latest_run ? menu.task : null;
  const { channels } = useChannels({ enabled: bluebirdEnabled });
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
      {analysisTask && <TaskAnalysisMenuItem Item={Item} task={analysisTask} />}
      {menu.onStop && (
        <Item onClick={menu.onStop}>
          <StopCircle size={14} />
          Stop task
        </Item>
      )}
      <Item
        disabled={!menu.onAddToCommandCenter}
        onClick={menu.onAddToCommandCenter}
      >
        <SquaresFourIcon size={14} />
        Add to Command Center…
      </Item>
      {channelItems.length > 0 && (isTask || menu.onFile) && (
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
                menu.kind === "canvas"
                  ? menu.onFile?.(channelId)
                  : fileToChannel(channelId, menu.id, menu.title)
              }
            />
          </MenuSubFlyout>
        </Sub>
      )}
      {isTask && menu.onHandoff && (
        <Item onClick={menu.onHandoff}>
          <UserSwitchIcon size={14} />
          Hand off…
        </Item>
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
  const holdSidebarPeek = useHoldSidebarPeek();
  const handleOpenChange = useCallback(
    (open: boolean): void => {
      if (!open || useSidebarPeekStore.getState().peek) {
        holdSidebarPeek(open);
      }
      onOpenChange?.(open);
    },
    [holdSidebarPeek, onOpenChange],
  );

  return (
    <ContextMenu onOpenChange={handleOpenChange}>
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
