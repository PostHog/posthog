import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import { CHANNEL_TASK_SUGGESTIONS } from "@posthog/ui/features/canvas/channelTaskSuggestions";
import { ChannelBreadcrumb } from "@posthog/ui/features/canvas/components/ChannelBreadcrumb";
import { ChannelContextPanel } from "@posthog/ui/features/canvas/components/ChannelContextPanel";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelTaskMutations } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import { useFolderInstructions } from "@posthog/ui/features/canvas/hooks/useFolderInstructions";
import { TaskInput } from "@posthog/ui/features/task-detail/components/TaskInput";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { Flex } from "@radix-ui/themes";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useCallback, useMemo, useState } from "react";

// A channel's "New task" view. Reuses /code's TaskInput, but routes the created
// task into the channel (/website/$channelId/tasks/$id) instead of /code, and
// files the task to the channel by creating an extra `task` row under the
// channel folder on the project's desktop_file_system surface.
export function WebsiteNewTask({ channelId }: { channelId: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { fileTask } = useChannelTaskMutations();
  const { channels } = useChannels();
  const channelName = channels.find((c) => c.id === channelId)?.name;

  // Surface the channel breadcrumb in the shared header, same as the other
  // channel scenes ("# channel / New task").
  useSetHeaderContent(
    useMemo(
      () => (
        <ChannelBreadcrumb
          channelName={channelName ?? "Channel"}
          channelId={channelId}
          leafLabel="New task"
        />
      ),
      [channelName, channelId],
    ),
  );
  // The channel's CONTEXT.md, passed to the agent as optional background so
  // tasks created here start with the shared context. Absent/empty is fine.
  const { data: instructions } = useFolderInstructions(channelId);
  const channelContext = instructions?.content;

  // Right-side preview of the CONTEXT.md, opened from the composer's chip so the
  // user can read what will be sent before submitting (mirrors the post-submit
  // context tab). Local view state — no panel-layout store exists pre-submit.
  const [contextPanelOpen, setContextPanelOpen] = useState(false);
  const [contextPanelWidth, setContextPanelWidth] = useState(360);
  const [contextPanelResizing, setContextPanelResizing] = useState(false);

  const handleContextChipClick = useCallback(() => {
    const nextOpen = !contextPanelOpen;
    setContextPanelOpen(nextOpen);
    // Only count opening the panel, not closing it, so an open→close→open
    // cycle doesn't inflate the metric.
    if (nextOpen) {
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "view_context",
        surface: "new_task",
        channel_id: channelId,
      });
    }
  }, [channelId, contextPanelOpen]);

  const onTaskCreated = useCallback(
    (task: Task) => {
      // Seed the detail cache so the destination route resolves instantly
      // (mirrors openTask), then file to the channel + navigate.
      queryClient.setQueryData(taskDetailQuery(task.id).queryKey, task);
      void fileTask(channelId, task.id, task.title)
        .then(() => {
          track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
            action_type: "file_task",
            surface: "new_task",
            channel_id: channelId,
            task_id: task.id,
            success: true,
          });
        })
        .catch((error: unknown) => {
          track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
            action_type: "file_task",
            surface: "new_task",
            channel_id: channelId,
            task_id: task.id,
            success: false,
          });
          toast.error("Couldn't file task to context", {
            description: error instanceof Error ? error.message : String(error),
          });
        });
      void navigate({
        to: "/website/$channelId/tasks/$taskId",
        params: { channelId, taskId: task.id },
      });
    },
    [channelId, fileTask, navigate, queryClient],
  );

  return (
    <Flex className="h-full min-w-0 flex-1">
      <div className="min-w-0 flex-1">
        <TaskInput
          onTaskCreated={onTaskCreated}
          channelContext={channelContext}
          channelName={channelName}
          channelContextId={channelId}
          allowNoRepo
          suggestions={CHANNEL_TASK_SUGGESTIONS}
          onSuggestionSelect={(label) =>
            track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
              action_type: "new_task_suggestion",
              surface: "new_task",
              channel_id: channelId,
              suggestion_label: label,
            })
          }
          onContextChipClick={
            channelContext ? handleContextChipClick : undefined
          }
        />
      </div>
      <ResizableSidebar
        open={contextPanelOpen && !!channelContext}
        width={contextPanelWidth}
        setWidth={setContextPanelWidth}
        isResizing={contextPanelResizing}
        setIsResizing={setContextPanelResizing}
        side="right"
      >
        {contextPanelOpen && channelContext ? (
          <ChannelContextPanel
            channelName={channelName}
            body={channelContext}
            onClose={() => setContextPanelOpen(false)}
          />
        ) : null}
      </ResizableSidebar>
    </Flex>
  );
}
