import { PointerSensor } from "@dnd-kit/dom";
import { type DragDropEvents, DragDropProvider } from "@dnd-kit/react";
import { useSortable } from "@dnd-kit/react/sortable";
import { CaretDown, CaretRight, Stack } from "@phosphor-icons/react";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { QueuedMessageView } from "@posthog/ui/features/sessions/components/session-update/QueuedMessageView";
import {
  useCancelQueuedMessageEdit,
  useEditQueuedMessage,
} from "@posthog/ui/features/sessions/hooks/useEditQueuedMessage";
import { useSupportsNativeSteer } from "@posthog/ui/features/sessions/hooks/useMessagingMode";
import {
  sessionStoreSetters,
  useSessionIsCloud,
  useSessionSelector,
  useSessionStore,
} from "@posthog/ui/features/sessions/sessionStore";
import {
  useQueueCollapsed,
  useSessionViewActions,
} from "@posthog/ui/features/sessions/sessionViewStore";
import { useQueuedMessagesForTask } from "@posthog/ui/features/sessions/useSession";
import { toast } from "@posthog/ui/primitives/toast";
import * as Collapsible from "@radix-ui/react-collapsible";
import { Box, Flex, Text } from "@radix-ui/themes";
import {
  type ReactNode,
  type RefCallback,
  useCallback,
  useEffect,
} from "react";

interface QueuedMessagesDockProps {
  taskId: string;
}

/**
 * A single queued card wrapped as a sortable item. Dragging is scoped to the
 * card's grip button (the handle ref passed to `children`), so the card's own
 * buttons never compete with a drag.
 */
function SortableQueuedMessage({
  id,
  index,
  taskId,
  children,
}: {
  id: string;
  index: number;
  taskId: string;
  children: (dragHandleRef: RefCallback<HTMLButtonElement>) => ReactNode;
}) {
  const { ref, handleRef, isDragging } = useSortable({
    id,
    index,
    group: `queue:${taskId}`,
    transition: { duration: 200, easing: "ease" },
  });

  return (
    <div ref={ref} style={{ opacity: isDragging ? 0.5 : 1 }}>
      {children(handleRef as RefCallback<HTMLButtonElement>)}
    </div>
  );
}

/**
 * Queued follow-ups pinned directly above the composer (outside the scrolling
 * thread) with per-message actions: steer it into the running turn now, edit it
 * in the composer while it stays queued, or discard it. Cards can be dragged to
 * reorder the queue — the order shown is the order they send.
 *
 * The list is bounded and scrolls internally so a long queue never pushes the
 * composer down or off-screen, and a header toggle lets the user collapse it.
 */
export function QueuedMessagesDock({ taskId }: QueuedMessagesDockProps) {
  const queued = useQueuedMessagesForTask(taskId);
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const supportsNativeSteer = useSupportsNativeSteer(taskId);
  const editMessage = useEditQueuedMessage(taskId);
  const cancelEdit = useCancelQueuedMessageEdit(taskId);
  const editingId = useSessionSelector(taskId, (s) => s?.editingQueuedId);
  // Narrow reads (not the whole session) so the dock doesn't re-render on every
  // streamed token while a turn is running.
  const isCompacting = useSessionSelector(
    taskId,
    (s) => s?.isCompacting ?? false,
  );
  const isCloud = useSessionIsCloud(taskId);
  // Steer can't inject mid-compaction, so it would be a silent no-op; hide it.
  // Cloud has no real mid-turn steer either (it would just interrupt the turn),
  // so hide it there too — the message stays queued and lands next turn.
  const canSteer = !isCompacting && !isCloud;
  const collapsed = useQueueCollapsed(taskId);
  const { setQueueCollapsed } = useSessionViewActions();

  // If the message being edited leaves the queue (e.g. discarded), drop the
  // stale edit hold so the composer sends normally and any messages the hold
  // was blocking can drain.
  useEffect(() => {
    if (editingId && !queued.some((m) => m.id === editingId)) {
      sessionService.clearEditingQueuedMessage(taskId);
    }
  }, [editingId, queued, taskId, sessionService]);

  const handleDragOver: DragDropEvents["dragover"] = useCallback(
    (event) => {
      const sourceId = event.operation.source?.id;
      const targetId = event.operation.target?.id;
      if (!sourceId || !targetId || sourceId === targetId) return;

      const state = useSessionStore.getState();
      const taskRunId = state.taskIdIndex[taskId];
      const queue = taskRunId
        ? (state.sessions[taskRunId]?.messageQueue ?? [])
        : [];
      const fromIndex = queue.findIndex((m) => m.id === sourceId);
      const toIndex = queue.findIndex((m) => m.id === targetId);
      if (fromIndex === -1 || toIndex === -1 || fromIndex === toIndex) return;

      sessionStoreSetters.moveQueuedMessage(taskId, fromIndex, toIndex);
    },
    [taskId],
  );

  if (queued.length === 0) return null;

  const isOpen = !collapsed;

  return (
    <Collapsible.Root
      open={isOpen}
      onOpenChange={(next) => setQueueCollapsed(taskId, !next)}
      className="mb-1"
    >
      <Collapsible.Trigger asChild>
        <button
          type="button"
          aria-label={
            isOpen ? "Collapse queued messages" : "Expand queued messages"
          }
          className="flex w-full items-center gap-2 rounded-sm px-1 py-0.5 text-left hover:bg-gray-3"
        >
          {isOpen ? (
            <CaretDown size={12} className="text-gray-10" />
          ) : (
            <CaretRight size={12} className="text-gray-10" />
          )}
          <Stack size={14} className="shrink-0 text-gray-9" />
          <Text className="font-medium text-[13px] text-gray-11">
            {queued.length} queued
          </Text>
        </button>
      </Collapsible.Trigger>
      <Collapsible.Content>
        <Box className="max-h-[30vh] overflow-y-auto">
          <DragDropProvider
            onDragOver={handleDragOver}
            sensors={[
              {
                plugin: PointerSensor,
                options: {
                  activationConstraints: { distance: { value: 5 } },
                },
              },
            ]}
          >
            <Flex direction="column" gap="1">
              {queued.map((message, index) => (
                <SortableQueuedMessage
                  key={message.id}
                  id={message.id}
                  index={index}
                  taskId={taskId}
                >
                  {(dragHandleRef) => (
                    <QueuedMessageView
                      message={message}
                      dragHandleRef={dragHandleRef}
                      supportsNativeSteer={supportsNativeSteer}
                      isEditing={editingId === message.id}
                      onSteer={
                        canSteer
                          ? () => {
                              void sessionService
                                .steerQueuedMessage(taskId, message.id)
                                .catch(() => {
                                  toast.error(
                                    "Couldn't steer this message. It's still queued.",
                                  );
                                });
                            }
                          : undefined
                      }
                      onEdit={() => editMessage(message)}
                      onCancelEdit={cancelEdit}
                      onRemove={() =>
                        sessionStoreSetters.removeQueuedMessage(
                          taskId,
                          message.id,
                        )
                      }
                    />
                  )}
                </SortableQueuedMessage>
              ))}
            </Flex>
          </DragDropProvider>
        </Box>
      </Collapsible.Content>
    </Collapsible.Root>
  );
}
