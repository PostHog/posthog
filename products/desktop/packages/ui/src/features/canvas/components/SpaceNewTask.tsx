import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import { CHANNEL_TASK_SUGGESTIONS } from "@posthog/ui/features/canvas/channelTaskSuggestions";
import { ChannelBreadcrumb } from "@posthog/ui/features/canvas/components/ChannelBreadcrumb";
import { ChannelContextPanel } from "@posthog/ui/features/canvas/components/ChannelContextPanel";
import { SpaceSelect } from "@posthog/ui/features/canvas/components/SpaceSelect";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useChannelTaskMutations } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import { useFolderInstructions } from "@posthog/ui/features/canvas/hooks/useFolderInstructions";
import { useTaskChannels } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useChannelWikiContext } from "@posthog/ui/features/context-wiki/hooks/useContextWiki";
import { useContextLayerFlag } from "@posthog/ui/features/feature-flags/useContextLayerFlag";
import { TaskInput } from "@posthog/ui/features/task-detail/components/TaskInput";
import { getTaskInputSessionId } from "@posthog/ui/features/task-detail/taskInputSession";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { toast } from "@posthog/ui/primitives/toast";
import { useAppView } from "@posthog/ui/router/useAppView";
import { track } from "@posthog/ui/shell/analytics";
import { Flex } from "@radix-ui/themes";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useCallback, useMemo, useState } from "react";

// A space's "New task" view. Reuses the shared TaskInput, but routes the
// created task into the space (/spaces/$channelId/tasks/$id) instead of the
// unscoped detail route, and files the task to the space (the task's `channel`
// field on the tasks API).
export function SpaceNewTask({ channelId }: { channelId: string }) {
  const spacesLayout = useChannelsLayout();
  const navigate = useNavigate();
  const view = useAppView();
  const tabId = useRouterState({
    select: (state) => state.location.state.tabId,
  });
  const taskInputSessionId = getTaskInputSessionId(tabId);
  const { fileTask } = useChannelTaskMutations();
  // The raw channel row also carries the space's repository defaults.
  const { channels } = useTaskChannels();
  const channel = channels.find((c) => c.id === channelId);
  const channelName = channel?.name;
  const contextLayerEnabled = useContextLayerFlag();
  const wiki = useChannelWikiContext(channelId, contextLayerEnabled);

  // Surface the channel breadcrumb in the shared header, same as the other
  // channel scenes ("# channel / New task").
  useSetHeaderContent(
    useMemo(
      () => (
        <ChannelBreadcrumb
          channelName={channelName ?? (spacesLayout ? "Space" : "Channel")}
          channelId={channelId}
          leafLabel="New task"
        />
      ),
      [channelName, channelId, spacesLayout],
    ),
  );
  // The channel's CONTEXT.md, passed to the agent as optional background so
  // tasks created here start with the shared context. Absent/empty is fine.
  const { data: instructions } = useFolderInstructions(channelId);
  const channelContext = wiki.useLegacy ? instructions?.content : undefined;

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

  const onTaskCreatedEffect = useCallback(
    (task: Task) => {
      void fileTask(channelId, task.id)
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
    },
    [channelId, fileTask],
  );

  // Retargeting navigates to that space's own new-task route. The draft is
  // scoped to the browser tab, so it survives this route change without
  // leaking into another new-task tab.
  const handleSpaceChange = useCallback(
    (nextChannelId: string) => {
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "new_task_open",
        surface: "new_task",
        channel_id: nextChannelId,
      });
      void navigate({
        to: "/spaces/$channelId/new",
        params: { channelId: nextChannelId },
      });
    },
    [navigate],
  );

  return (
    <Flex className="h-full min-w-0 flex-1">
      <div className="min-w-0 flex-1">
        <TaskInput
          key={taskInputSessionId}
          sessionId={taskInputSessionId}
          // Beside the Cloud/Local chip: which space the task files into.
          // Arriving from a space's own "+" this is pre-filled; the global
          // new-task entry points land on #me.
          spaceSelector={({ disabled }) => (
            <SpaceSelect
              value={channelId}
              onChange={handleSpaceChange}
              disabled={disabled}
            />
          )}
          onTaskCreatedEffect={onTaskCreatedEffect}
          channelContext={channelContext}
          channelContextPath={wiki.path}
          channelContextBlocked={wiki.blocked}
          channelContextFailed={wiki.failed}
          channelContextUnavailable={wiki.unavailable}
          onChannelContextRetry={wiki.retry}
          channelName={channelName}
          channelId={channelId}
          channelContextId={channelId}
          allowNoRepo
          channelRepositories={channel?.repositories}
          channelGithubIntegration={channel?.github_integration}
          // So a prompt handed to openTaskInput survives routing into a channel.
          initialPrompt={view.initialPrompt}
          initialPromptKey={view.taskInputRequestId}
          initialCloudRepository={view.initialCloudRepository}
          initialModel={view.initialModel}
          initialMode={view.initialMode}
          reportAssociation={view.reportAssociation}
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
