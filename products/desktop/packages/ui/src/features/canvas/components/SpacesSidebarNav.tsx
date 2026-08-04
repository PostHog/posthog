import { PointerSensor } from "@dnd-kit/dom";
import { type DragDropEvents, DragDropProvider } from "@dnd-kit/react";
import { useSortable } from "@dnd-kit/react/sortable";
import { PlusIcon } from "@phosphor-icons/react";
import {
  Button,
  Switch,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { AllSpacesSection } from "@posthog/ui/features/canvas/components/AllSpacesSection";
import { ChannelNav } from "@posthog/ui/features/canvas/components/ChannelNav";
import { MyTasksSection } from "@posthog/ui/features/canvas/components/MyTasksSection";
import { SpaceSection } from "@posthog/ui/features/canvas/components/SpaceSection";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useStarredChannelSlots } from "@posthog/ui/features/canvas/hooks/useStarredChannelSlots";
import { PERSONAL_CHANNEL_NAME } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useSpacesSidebarStore } from "@posthog/ui/features/canvas/stores/spacesSidebarStore";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import type { RefCallback } from "react";
import { useMemo } from "react";

/**
 * One sortable pinned space. The header row is the drag handle (via
 * SpaceSection's dragHandleRef), so the task rows keep their own native drag
 * into the Command Center. #me renders outside this wrapper — it's always
 * first and doesn't reorder.
 */
function SortableSpace({ space, index }: { space: Channel; index: number }) {
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
  const currentChannelId = useCurrentChannelStore((s) => s.currentChannelId);

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

  const handleDragEnd: DragDropEvents["dragend"] = (event) => {
    if (event.canceled) return;
    const sourceId = event.operation.source?.id;
    const targetId = event.operation.target?.id;
    if (!sourceId || !targetId || sourceId === targetId) return;
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

      {/* The create entry point, now that the floating button is gone. Files
          into the space you're in; the composer's space selector can retarget
          it. */}
      <div className="shrink-0 px-2 pb-1.5">
        <Button
          variant="outline"
          size="sm"
          className="w-full justify-start gap-1.5"
          onClick={() => {
            track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
              action_type: "new_task_open",
              surface: "sidebar",
              channel_id: currentChannelId ?? me?.id,
            });
            openTaskInput({
              channelId: currentChannelId ?? me?.id,
              space: "website",
            });
          }}
        >
          <PlusIcon size={14} />
          New session
        </Button>
      </div>

      {/* The viewer's tasks across every space. */}
      <div className="shrink-0 px-2 pb-1">
        <MyTasksSection />
      </div>

      {/* The section label, with one filter over every space's task list. */}
      <div className="flex shrink-0 items-center justify-between px-3 pb-1.5 text-[12px] text-muted-foreground">
        Spaces
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
      </div>

      {/* Pinned (starred) spaces; #me first and fixed, the rest reorderable. */}
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        <div className="flex flex-col gap-px">
          {me && <SpaceSection channel={me} />}
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
              <SortableSpace key={space.id} space={space} index={index} />
            ))}
          </DragDropProvider>
        </div>
      </div>

      {/* Every space in the project, docked at the bottom. */}
      <AllSpacesSection />
    </div>
  );
}
