import { insertTaskDedup } from "@posthog/core/tasks/taskDelete";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import { isTerminalStatus } from "@posthog/shared/domain-types";
import { CHANNEL_TASK_SUGGESTIONS } from "@posthog/ui/features/canvas/channelTaskSuggestions";
import {
  ChannelFeedView,
  type PendingKickoff,
} from "@posthog/ui/features/canvas/components/ChannelFeedView";
import { ChannelHeader } from "@posthog/ui/features/canvas/components/ChannelHeader";
import {
  ChannelHomeComposer,
  type ChannelHomeComposerHandle,
} from "@posthog/ui/features/canvas/components/ChannelHomeComposer";
import {
  ChannelIntro,
  type ContextMdState,
} from "@posthog/ui/features/canvas/components/ChannelIntro";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import { ThreadSidebar } from "@posthog/ui/features/canvas/components/ThreadSidebar";
import { CONTEXT_MD_TASK_TITLE_PREFIX } from "@posthog/ui/features/canvas/contextPrompt";
import {
  channelFeedQueryKey,
  useChannelFeed,
} from "@posthog/ui/features/canvas/hooks/useChannelFeed";
import {
  channelCreationMessage,
  useChannelFeedMessages,
} from "@posthog/ui/features/canvas/hooks/useChannelFeedMessages";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelTaskMutations } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import { useFolderInstructions } from "@posthog/ui/features/canvas/hooks/useFolderInstructions";
import {
  PERSONAL_CHANNEL_NAME,
  useBackendChannel,
} from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useThreadPanelStore } from "@posthog/ui/features/canvas/stores/threadPanelStore";
import { SuggestedPromptCard } from "@posthog/ui/features/task-detail/components/SuggestedPromptCard";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { Heading, Text } from "@radix-ui/themes";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useCallback, useMemo, useRef, useState } from "react";

// A channel: a Slack-style multiplayer feed. Each member message kicks off a
// task rendered as a card everyone in the channel sees; the composer stays
// pinned at the bottom and threads open in a right-hand panel. The channel's
// artifacts/history/context views stay in the tabs above (ChannelHeader).
export function WebsiteChannelHome({ channelId }: { channelId: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { channels, isLoading: isLoadingChannels } = useChannels();
  const channelName = channels.find((c) => c.id === channelId)?.name;
  const { fileTask } = useChannelTaskMutations();

  // Poll while empty so the intro's context.md card flips to "created" when
  // the agent publishes mid plan-session, without a manual reload.
  const { data: instructions, isLoading: isLoadingInstructions } =
    useFolderInstructions(channelId, { pollWhileEmpty: true });
  const channelContext = instructions?.content;

  // The folder channel maps onto a backend channel (by name; "me" → the
  // personal channel), which owns the task feed and threads.
  const { channel: backendChannel, isLoading: isResolvingChannel } =
    useBackendChannel(channelName);
  const { tasks, isLoading: isLoadingFeed } = useChannelFeed(
    backendChannel?.id,
  );
  // Marking this channel read lives in ChannelHeader (rendered by every channel
  // surface), so opening Artifacts or CONTEXT.md counts as reading it too.

  // Durable "PostHog agent" rows (CONTEXT.md being built, …) live on the
  // backend channel — the same id the feed tasks use, not the folder id.
  const { messages: feedMessages, isLoading: isLoadingMessages } =
    useChannelFeedMessages(backendChannel?.id);
  // Until the backend channel resolves there's no feed to ask for, and the feed
  // query is disabled — which reports isLoading:false, indistinguishable from
  // "this channel is empty". useBackendChannel reports loading for the whole
  // identity-resolution window (settling if the resolve fails), so fold it in:
  // we can't call a channel empty until we know which channel it is.
  const isLoading =
    isLoadingChannels ||
    isResolvingChannel ||
    isLoadingFeed ||
    isLoadingMessages;
  // The Slack-style "joined" opener, derived from the channel row so it renders
  // (and sorts first) even where the feed endpoint isn't deployed.
  const systemMessages = useMemo(() => {
    const creation = channelCreationMessage(backendChannel);
    return creation ? [creation, ...feedMessages] : feedMessages;
  }, [backendChannel, feedMessages]);

  useSetHeaderContent(
    useMemo(() => <ChannelHeader channelId={channelId} />, [channelId]),
  );

  const composerRef = useRef<ChannelHomeComposerHandle>(null);

  // Optimistic kickoffs: the message a user just submitted, shown in the feed
  // with a "Starting…" card while its task is created in the background. Each
  // is tagged with the channel it was fired in and filtered to the current one,
  // so a still-in-flight kickoff never bleeds into another channel's feed.
  const [pending, setPending] = useState<
    (PendingKickoff & { channelId: string })[]
  >([]);
  const addPending = useCallback(
    (kickoff: PendingKickoff) => {
      setPending((prev) => [...prev, { ...kickoff, channelId }]);
    },
    [channelId],
  );
  const removePending = useCallback((id: string) => {
    setPending((prev) => prev.filter((p) => p.id !== id));
  }, []);
  const visiblePending = useMemo(
    () => pending.filter((p) => p.channelId === channelId),
    [pending, channelId],
  );

  // The "Create your context.md" dialog, opened from the welcome message's
  // onboarding checklist. Describe-mode: seeds a plan session for this context.
  const [contextMdDialogOpen, setContextMdDialogOpen] = useState(false);

  const threadTaskId = useThreadPanelStore(
    (s) => s.openByChannel[channelId] ?? null,
  );
  const openThread = useThreadPanelStore((s) => s.openThread);
  const closeThread = useThreadPanelStore((s) => s.closeThread);

  const handleSuggestionSelect = useCallback(
    (prompt: string, mode?: string) => {
      composerRef.current?.applySuggestion(prompt, mode);
    },
    [],
  );

  const invalidateFeed = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: channelFeedQueryKey(backendChannel?.id),
    });
  }, [queryClient, backendChannel?.id]);

  // Slack behavior: submitting keeps you in the channel; the new card appears
  // in the feed and updates live. Filing into the folder keeps the Artifacts /
  // Recents tabs working.
  const onTaskCreated = useCallback(
    (task: Task) => {
      queryClient.setQueryData(taskDetailQuery(task.id).queryKey, task);
      // Splice the real card straight into the feed so it appears now rather
      // than after the invalidate refetch (or the next 5s poll) lands. Seed a
      // fresh list when the feed cache hasn't populated yet — insertTaskDedup
      // no-ops on an undefined cache, which would otherwise drop the card.
      queryClient.setQueryData<Task[]>(
        channelFeedQueryKey(backendChannel?.id),
        (old) => (old ? insertTaskDedup(old, task) : [task]),
      );
      invalidateFeed();
      void fileTask(channelId, task.id, task.title)
        .then(() =>
          track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
            action_type: "file_task",
            surface: "channel_home",
            channel_id: channelId,
            task_id: task.id,
            success: true,
          }),
        )
        .catch((error: unknown) => {
          track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
            action_type: "file_task",
            surface: "channel_home",
            channel_id: channelId,
            task_id: task.id,
            success: false,
          });
          toast.error("Couldn't file task to channel", {
            description: error instanceof Error ? error.message : String(error),
          });
        });
    },
    [backendChannel?.id, channelId, fileTask, invalidateFeed, queryClient],
  );

  const handleOpenFull = useCallback(
    (taskId: string) => {
      void navigate({
        to: "/website/$channelId/tasks/$taskId",
        params: { channelId, taskId },
      });
    },
    [channelId, navigate],
  );
  const handleOpenTask = useCallback(
    (task: Task) => handleOpenFull(task.id),
    [handleOpenFull],
  );

  const handleOpenThread = useCallback(
    (task: Task) => openThread(channelId, task.id),
    [channelId, openThread],
  );

  const threadTask = threadTaskId
    ? tasks.find((t) => t.id === threadTaskId)
    : undefined;

  // The Slack-style intro pinned at the feed's start — public channels only;
  // the personal channel keeps the welcome empty state below.
  const isPersonal = channelName === PERSONAL_CHANNEL_NAME;
  const hasContextMd = (channelContext ?? "").trim().length > 0;
  // An in-flight build is spotted by its plan task in this channel's feed (by
  // title prefix — the only task↔context.md tie until the backend links them),
  // so the intro card can show "Creating…" instead of a second "Create" CTA.
  // Drafts with no run are ignored: a half-launched task shouldn't pin the
  // card in the building state with no way to retry.
  const isBuildingContextMd = tasks.some(
    (t) =>
      t.title?.startsWith(CONTEXT_MD_TASK_TITLE_PREFIX) &&
      t.latest_run &&
      !isTerminalStatus(t.latest_run.status),
  );
  const contextMdState: ContextMdState = hasContextMd
    ? "created"
    : isLoadingInstructions
      ? "loading"
      : isBuildingContextMd
        ? "building"
        : "none";
  const intro =
    !isPersonal && channelName && backendChannel ? (
      <ChannelIntro
        channel={backendChannel}
        channelName={channelName}
        contextMdState={contextMdState}
        onCreateContextMd={() => setContextMdDialogOpen(true)}
      />
    ) : undefined;

  const emptyState = (
    <div className="mx-auto flex min-h-full w-full max-w-[680px] flex-col justify-center gap-6 px-4 py-10">
      <div className="flex flex-col items-center gap-2 text-center">
        <Heading className="font-bold text-2xl">
          {channelName === PERSONAL_CHANNEL_NAME
            ? "Welcome to your own personal context"
            : channelName
              ? `Welcome to ${channelName}`
              : "Welcome"}
        </Heading>
        <Text>
          Contexts are for areas of work. Context.md is self-updating, so start
          some work and the context file will update itself.
        </Text>
      </div>
      <div className="flex flex-col gap-2">
        <Text size="1" weight="medium" className="px-1 text-(--gray-11)">
          Suggestions
        </Text>
        <div className="grid grid-cols-2 gap-2">
          {CHANNEL_TASK_SUGGESTIONS.map((suggestion) => (
            <SuggestedPromptCard
              key={suggestion.label}
              suggestion={suggestion}
              onSelect={() =>
                handleSuggestionSelect(suggestion.prompt, suggestion.mode)
              }
            />
          ))}
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex h-full min-w-0 bg-gray-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <ChannelFeedView
          channelId={channelId}
          tasks={tasks}
          pending={visiblePending}
          systemMessages={systemMessages}
          isLoading={isLoading}
          emptyState={emptyState}
          intro={intro}
          onOpenTask={handleOpenTask}
          onOpenThread={handleOpenThread}
        />
        <div className="mx-auto w-full px-4 pb-4">
          <ChannelHomeComposer
            ref={composerRef}
            channelId={channelId}
            channelName={channelName}
            channelContext={channelContext}
            backendChannelId={backendChannel?.id}
            onTaskCreated={onTaskCreated}
            onPendingStart={addPending}
            onPendingEnd={removePending}
          />
        </div>
      </div>

      {threadTaskId && (
        <ThreadSidebar
          taskId={threadTaskId}
          channelId={channelId}
          task={threadTask}
          onClose={() => closeThread(channelId)}
          onOpenFull={() => handleOpenFull(threadTaskId)}
        />
      )}

      {channelName && (
        <CreateChannelModal
          open={contextMdDialogOpen}
          onOpenChange={setContextMdDialogOpen}
          existingContext={{ channelId, channelName }}
        />
      )}
    </div>
  );
}
