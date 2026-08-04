import { CaretRightIcon } from "@phosphor-icons/react";
import {
  Button,
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubTrigger,
  ContextMenuTrigger,
  DropdownMenu,
  DropdownMenuTrigger,
  Separator,
} from "@posthog/quill";
import { PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useFileTaskToChannel } from "@posthog/ui/features/canvas/hooks/useFileTaskToChannel";
import { useSpacesSidebarStore } from "@posthog/ui/features/canvas/stores/spacesSidebarStore";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import {
  type MenuFlyoutItem,
  MenuSubFlyout,
  SearchableMenuFlyout,
} from "@posthog/ui/primitives/SearchableMenuFlyout";
import { toast } from "@posthog/ui/primitives/toast";
import { type ComponentType, Fragment, type ReactNode, useMemo } from "react";

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
  onTogglePin: () => void;
  /** Present only on watch-list rows — forgets the local reference. */
  onRemoveFromWatchList?: () => void;
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
  Separator: ComponentType;
}

const CONTEXT_PARTS: MenuParts = {
  Item: ContextMenuItem,
  Sub: ContextMenuSub,
  SubTrigger: ContextMenuSubTrigger,
  Separator: ContextMenuSeparator,
};

/**
 * The row's actions in three groups, separated by a rule:
 *   1. mark it       — pin, watch, rename (things you do to the item in place)
 *   2. send it       — Command Center, File to… (put it somewhere else)
 *   3. remove it     — archive, delete (get rid of it)
 * A group with nothing in it (a canvas has no "send" actions) drops out along
 * with the separator that would have led it, so the rule never floats alone.
 */
function TaskRowMenuItems({
  parts,
  menu,
}: {
  parts: MenuParts;
  menu: TaskRowMenuProps;
}) {
  const { Item, Sub, SubTrigger, Separator } = parts;
  // "File to…" is a Project Bluebird feature; gate the channel fetch behind the
  // flag so neither the submenu nor its request reaches ungated users.
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  const isTask = menu.kind === "task";
  const { channels } = useChannels({ enabled: bluebirdEnabled && isTask });
  const fileToChannel = useFileTaskToChannel();

  // The watch list is a global view store, so any task row can toggle it — no
  // need to thread a handler through every list. Watch-list rows still pass an
  // explicit remover (they know their own context), which wins.
  const watchList = useSpacesSidebarStore((s) => s.watchList);
  const addToWatchList = useSpacesSidebarStore((s) => s.addToWatchList);
  const removeFromWatchList = useSpacesSidebarStore(
    (s) => s.removeFromWatchList,
  );
  const isWatched = isTask && watchList.some((entry) => entry.id === menu.id);

  const channelItems: MenuFlyoutItem[] = channels.map((channel) => ({
    id: channel.id,
    label: channel.name,
    current: channel.id === menu.channelId,
  }));

  // Sits with Pin — both are "keep an eye on this", not a place to send it to.
  const removeWatch =
    menu.onRemoveFromWatchList ?? (() => removeFromWatchList(menu.id));
  const watchItem = !isTask ? null : isWatched || menu.onRemoveFromWatchList ? (
    <Item key="watch" onClick={removeWatch}>
      Remove from watch list
    </Item>
  ) : (
    <Item
      key="watch"
      onClick={() => {
        addToWatchList({ id: menu.id, title: menu.title, addedAt: Date.now() });
        toast.success("Added to watch list", { description: menu.title });
      }}
    >
      Add to watch list
    </Item>
  );

  const groups: { key: string; items: ReactNode[] }[] = [
    {
      key: "mark",
      items: [
        <Item key="pin" onClick={menu.onTogglePin}>
          {menu.isPinned ? "Unpin" : "Pin"}
        </Item>,
        watchItem,
        menu.onRename ? (
          <Item key="rename" onClick={menu.onRename}>
            Rename
          </Item>
        ) : null,
      ],
    },
    {
      key: "send",
      items: [
        isTask ? (
          <Item
            key="cc"
            disabled={!menu.onAddToCommandCenter}
            onClick={menu.onAddToCommandCenter}
          >
            Add to Command Center
          </Item>
        ) : null,
        isTask && channelItems.length > 0 ? (
          <Sub key="file">
            <SubTrigger>File to…</SubTrigger>
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
        ) : null,
      ],
    },
    {
      key: "remove",
      items: [
        menu.onArchive ? (
          <Item key="archive" onClick={menu.onArchive}>
            Archive
          </Item>
        ) : null,
        // The ellipsis is the promise that a confirm follows — deleting a
        // canvas takes it away from everyone in the space.
        menu.onDelete ? (
          <Item key="delete" variant="destructive" onClick={menu.onDelete}>
            Delete…
          </Item>
        ) : null,
      ],
    },
  ];

  const visible = groups
    .map((group) => ({ key: group.key, items: group.items.filter(Boolean) }))
    .filter((group) => group.items.length > 0);

  return (
    <>
      {visible.map((group, index) => (
        <Fragment key={group.key}>
          {index > 0 && <Separator />}
          {group.items}
        </Fragment>
      ))}
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
          size="sm"
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
            <Button variant="default" size="sm" left className="w-full">
              <span className="flex-1 text-left">{children}</span>
              <CaretRightIcon size={12} />
            </Button>
          }
        />
      ),
      Separator: () => <Separator className="my-1" />,
    }),
    [onAction, onSubmenuOpenChange],
  );

  return (
    <div className="flex flex-col">
      <TaskRowMenuItems parts={parts} menu={menu} />
    </div>
  );
}

/** The same menu on right-click, wrapping the row. */
export function TaskRowContextMenu({
  menu,
  children,
}: {
  menu: TaskRowMenuProps;
  children: ReactNode;
}) {
  return (
    <ContextMenu>
      <ContextMenuTrigger render={<div className="min-w-0" />}>
        {children}
      </ContextMenuTrigger>
      <ContextMenuContent className="w-56">
        <TaskRowMenuItems parts={CONTEXT_PARTS} menu={menu} />
      </ContextMenuContent>
    </ContextMenu>
  );
}
