import { PointerSensor } from "@dnd-kit/dom";
import { type DragDropEvents, DragDropProvider } from "@dnd-kit/react";
import { useSortable } from "@dnd-kit/react/sortable";
import { MagnifyingGlass, PlusIcon } from "@phosphor-icons/react";
import {
  Button,
  cn,
  Input,
  MenuLabel,
  Separator,
  Switch,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { AllSpacesSection } from "@posthog/ui/features/canvas/components/AllSpacesSection";
import { ChannelNav } from "@posthog/ui/features/canvas/components/ChannelNav";
import { SpaceSection } from "@posthog/ui/features/canvas/components/SpaceSection";
import { WatchListSection } from "@posthog/ui/features/canvas/components/WatchListSection";
import {
  useChannelStarMutations,
  useChannelStars,
} from "@posthog/ui/features/canvas/hooks/useChannelStars";
import {
  type Channel,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { useStarredChannelSlots } from "@posthog/ui/features/canvas/hooks/useStarredChannelSlots";
import { PERSONAL_CHANNEL_NAME } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useSpacesSidebarStore } from "@posthog/ui/features/canvas/stores/spacesSidebarStore";
import { toast } from "@posthog/ui/primitives/toast";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import type { DragEvent, RefCallback } from "react";
import { useMemo, useState } from "react";

/**
 * One sortable pinned space. The header row is the drag handle (via
 * SpaceSection's dragHandleRef), so the task rows keep their own native drag
 * into the Command Center. #me renders outside this wrapper — it's always
 * first and doesn't reorder.
 */
function SortableSpace({
  space,
  index,
  query,
}: {
  space: Channel;
  index: number;
  query?: string;
}) {
  const { ref, handleRef, isDragging } = useSortable({
    id: space.id,
    index,
    group: "pinned-spaces",
    transition: { duration: 200, easing: "ease" },
  });

  return (
    <div ref={ref} style={{ opacity: isDragging ? 0.5 : 1 }}>
      <SpaceSection
        channel={space}
        dragHandleRef={handleRef as RefCallback<HTMLButtonElement>}
        query={query}
      />
    </div>
  );
}

/**
 * The static spaces nav: the shell keeps ChannelNav (the highlighted icon
 * row — Inbox, Activity, Command Center and Settings already live there),
 * then the Spaces section header with its my-tasks filter, then every pinned
 * space with its tasks foldable inline — drag a space's row to reorder. The
 * All spaces directory is docked at the bottom and opens upward; the pinned
 * list is what scrolls in between.
 */
export function SpacesSidebarNav() {
  const { slots: pinnedSpaces } = useStarredChannelSlots();
  const onlyMyTasks = useSpacesSidebarStore((s) => s.onlyMyTasks);
  const toggleOnlyMyTasks = useSpacesSidebarStore((s) => s.toggleOnlyMyTasks);
  const spaceOrder = useSpacesSidebarStore((s) => s.spaceOrder);
  const setSpaceOrder = useSpacesSidebarStore((s) => s.setSpaceOrder);
  // One search over every space's task list; transient view state.
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchText, setSearchText] = useState("");
  const query = searchOpen
    ? searchText.trim().toLowerCase() || undefined
    : undefined;

  // Dropping an All-spaces row into this region pins it (stars it), same as
  // the directory's star but as one gesture; dragging a pinned row out again
  // unpins it.
  const { channels } = useChannels();
  const { starredRefToShortcutId } = useChannelStars();
  const { star, unstar } = useChannelStarMutations();
  const [isSpaceDropTarget, setIsSpaceDropTarget] = useState(false);

  const me = pinnedSpaces.find((c) => c.name === PERSONAL_CHANNEL_NAME);
  // The user's drag order over the starred set; spaces they've never dragged
  // keep their backend order after the ranked ones (sort is stable).
  const orderedSpaces = useMemo(() => {
    const starred = pinnedSpaces.filter(
      (c) => c.name !== PERSONAL_CHANNEL_NAME,
    );
    const rank = new Map(spaceOrder.map((id, index) => [id, index]));
    return [...starred].sort(
      (a, b) =>
        (rank.get(a.id) ?? Number.MAX_SAFE_INTEGER) -
        (rank.get(b.id) ?? Number.MAX_SAFE_INTEGER),
    );
  }, [pinnedSpaces, spaceOrder]);

  const handleSpaceDragOver = (e: DragEvent) => {
    if (!e.dataTransfer.types.includes("text/x-space-id")) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    setIsSpaceDropTarget(true);
  };
  const handleSpaceDragLeave = (e: DragEvent) => {
    // dragleave fires when crossing into children; only clear on a real exit.
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
    setIsSpaceDropTarget(false);
  };
  const handleSpaceDrop = (e: DragEvent) => {
    setIsSpaceDropTarget(false);
    const spaceId = e.dataTransfer.getData("text/x-space-id");
    if (!spaceId) return;
    e.preventDefault();
    const channel = channels.find((c) => c.id === spaceId);
    if (!channel || starredRefToShortcutId.has(channel.path)) return;
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "star",
      surface: "sidebar",
      channel_id: channel.id,
    });
    star(channel).catch((error: unknown) =>
      toast.error("Couldn't pin space", {
        description: error instanceof Error ? error.message : String(error),
      }),
    );
    // Pins land at the bottom of the user's order, ready to drag into place.
    setSpaceOrder([
      ...orderedSpaces.map((c) => c.id).filter((id) => id !== spaceId),
      spaceId,
    ]);
  };

  const handleDragEnd: DragDropEvents["dragend"] = (event) => {
    if (event.canceled) return;
    const sourceId = event.operation.source?.id;
    const targetId = event.operation.target?.id;
    if (!sourceId) return;
    // Released over no pinned row — the drag left the list, which unpins.
    // In-place drops are safe: the row under the pointer (itself included)
    // is still the target.
    if (!targetId) {
      const channel = channels.find((c) => c.id === String(sourceId));
      const shortcutId = channel && starredRefToShortcutId.get(channel.path);
      if (!channel || !shortcutId) return;
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "unstar",
        surface: "sidebar",
        channel_id: channel.id,
      });
      unstar(shortcutId).catch((error: unknown) =>
        toast.error("Couldn't unpin space", {
          description: error instanceof Error ? error.message : String(error),
        }),
      );
      setSpaceOrder(
        orderedSpaces.map((c) => c.id).filter((id) => id !== channel.id),
      );
      return;
    }
    if (sourceId === targetId) return;
    const ids = orderedSpaces.map((c) => c.id);
    const from = ids.indexOf(String(sourceId));
    const to = ids.indexOf(String(targetId));
    if (from < 0 || to < 0) return;
    ids.splice(to, 0, ...ids.splice(from, 1));
    setSpaceOrder(ids);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ChannelNav />

      {/* The create entry point, now that the floating button is gone. The
          global button defaults to #me — the composer's space chip is where
          to retarget; a space's own "+" pre-fills that space instead. */}
      <div className="shrink-0 px-2 pb-1.5">
        {/* quill's outline treatment — a step above the flat rows without
            primary's shout; centered, sized like the sm rows around it. */}
        <Button
          variant="outline"
          size="sm"
          className="w-full gap-1.5"
          onClick={() => {
            track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
              action_type: "new_task_open",
              surface: "sidebar",
              channel_id: me?.id,
            });
            openTaskInput({ channelId: me?.id, space: "website" });
          }}
        >
          <PlusIcon size={14} weight="bold" />
          New session
        </Button>
      </div>

      {/* Dragged-in task references, kept locally. */}
      <div className="shrink-0 px-2">
        <WatchListSection />
      </div>

      <Separator className="my-1 shrink-0" />

      {/* The section label, with search and one filter over every space's
          task list. Searching swaps the label for the input on the same row —
          the header holds its line either way; the Mine switch steps aside
          for the input's width and returns on close. */}
      <div className="flex min-h-8 shrink-0 items-center justify-between gap-1.5 px-2 pr-3">
        {searchOpen ? (
          <Input
            autoFocus
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setSearchOpen(false);
                setSearchText("");
              }
            }}
            placeholder="Search all spaces…"
            aria-label="Search tasks in all spaces"
            className="h-6 min-w-0 flex-1 text-[12px]"
          />
        ) : (
          <MenuLabel>Spaces</MenuLabel>
        )}
        <div className="flex shrink-0 items-center gap-1.5">
          <Button
            variant="default"
            size="icon-xs"
            aria-label="Search all spaces"
            aria-pressed={searchOpen}
            onClick={() => {
              setSearchOpen((prev) => !prev);
              setSearchText("");
            }}
            className={cn(
              "text-muted-foreground",
              searchOpen && "bg-fill-selected text-foreground",
            )}
          >
            <MagnifyingGlass size={12} />
          </Button>
          {!searchOpen && (
            <>
              <span className="text-[12px] text-muted-foreground">Mine</span>
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Switch
                      size="sm"
                      aria-label="Only show my tasks"
                      checked={onlyMyTasks}
                      onCheckedChange={toggleOnlyMyTasks}
                    />
                  }
                />
                <TooltipContent side="bottom">
                  {onlyMyTasks
                    ? "Showing only your tasks — switch off to see everyone's"
                    : "Only show tasks you created, in every space"}
                </TooltipContent>
              </Tooltip>
            </>
          )}
        </div>
      </div>

      {/* Pinned (starred) spaces; #me first and fixed, the rest reorderable.
          This region is the sidebar's one scroll container — spaces unfold
          their full lists inside it, so there are no nested scrollbars. It
          also accepts All-spaces rows dragged up from the directory below. */}
      {/* biome-ignore lint/a11y/noStaticElementInteractions: drop target for space drags; the directory's star is the keyboard path */}
      <div
        className={cn(
          "min-h-0 flex-1 overflow-y-auto px-2 pb-2 transition-colors",
          isSpaceDropTarget && "bg-fill-hover",
        )}
        onDragOver={handleSpaceDragOver}
        onDragLeave={handleSpaceDragLeave}
        onDrop={handleSpaceDrop}
      >
        <div className="flex flex-col gap-px">
          {me && <SpaceSection channel={me} query={query} />}
          {/* The handle doubles as the fold toggle, so a small pickup
              distance keeps plain clicks from starting a drag. */}
          <DragDropProvider
            onDragEnd={handleDragEnd}
            sensors={[
              {
                plugin: PointerSensor,
                options: { activationConstraints: { distance: { value: 5 } } },
              },
            ]}
          >
            {orderedSpaces.map((space, index) => (
              <SortableSpace
                key={space.id}
                space={space}
                index={index}
                query={query}
              />
            ))}
          </DragDropProvider>
        </div>
      </div>

      {/* Every space in the project, docked at the bottom. */}
      <AllSpacesSection />
    </div>
  );
}
