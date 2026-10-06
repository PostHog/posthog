import {
  buildChannelItems,
  DEFAULT_CHANNEL_ITEM_FILTERS,
} from "@posthog/core/canvas/channelItems";
import { isPersonalChannel } from "@posthog/core/canvas/channelName";
import { insertTaskDedup } from "@posthog/core/tasks/taskDelete";
import { cn } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import { isTerminalStatus } from "@posthog/shared/domain-types";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
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
import { SpaceActivityControls } from "@posthog/ui/features/canvas/components/work/SpaceActivityControls";
import { useSpacePullRequests } from "@posthog/ui/features/canvas/components/work/useSpacePullRequests";
import { CONTEXT_MD_TASK_TITLE_PREFIX } from "@posthog/ui/features/canvas/contextPrompt";
import {
  channelFeedQueryKey,
  useChannelFeed,
} from "@posthog/ui/features/canvas/hooks/useChannelFeed";
import { useChannelFeedMessages } from "@posthog/ui/features/canvas/hooks/useChannelFeedMessages";
import { useChannelSessionFacts } from "@posthog/ui/features/canvas/hooks/useChannelItems";
import {
  DEFAULT_CHANNEL_REPORTS_FILTERS,
  useChannelReports,
} from "@posthog/ui/features/canvas/hooks/useChannelReports";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useChannelTaskMutations } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import { useDashboards } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useFolderInstructions } from "@posthog/ui/features/canvas/hooks/useFolderInstructions";
import { useTaskChannels } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useChannelIntroStore } from "@posthog/ui/features/canvas/stores/channelIntroStore";
import { useSpaceActivityViewStore } from "@posthog/ui/features/canvas/stores/spaceActivityViewStore";
import {
  type ThreadPanelTab,
  useThreadPanelStore,
} from "@posthog/ui/features/canvas/stores/threadPanelStore";
import { openRightPanelSide } from "@posthog/ui/features/navigation/rightPanelSide";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { SuggestedPromptCard } from "@posthog/ui/features/task-detail/components/SuggestedPromptCard";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { toast } from "@posthog/ui/primitives/toast";
import { navigateToChannelReportDetail } from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

const NO_TASKS: Task[] = [];

// A channel: a multiplayer feed. Each member message kicks off a task rendered
// as a card everyone in the channel sees; the composer stays pinned at the top
// (Twitter-style — new session first, newest cards under it) and threads open
// in a right-hand panel. The channel's artifacts/history/context views stay in
// the tabs above (ChannelHeader).
export function WebsiteChannelHome({
  channelId,
  variant = "feed",
}: {
  channelId: string;
  variant?: "feed" | "work";
}) {
  const spacesLayout = useChannelsLayout();
  const isWork = variant === "work";
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // The raw channel row (creator + creation time) feeds the intro and the
  // Slack-style "joined" opener; the Channel projection doesn't carry those.
  const { channels, isLoading: isLoadingChannels } = useTaskChannels();
  const channel = channels.find((c) => c.id === channelId);
  const channelName = channel?.name;
  const { fileTask } = useChannelTaskMutations();

  // Poll while empty so the intro's context.md card flips to "created" when
  // the agent publishes mid plan-session, without a manual reload.
  const { data: instructions, isLoading: isLoadingInstructions } =
    useFolderInstructions(channelId, { pollWhileEmpty: true });
  const channelContext = instructions?.content;

  const { tasks, isLoading: isLoadingFeed } = useChannelFeed(channelId);
  const { dashboards: spaceCanvases } = useDashboards(channelId);
  const archivedTaskIds = useArchivedTaskIds();
  const { pinnedTaskIds } = usePinnedTasks();
  const sessionFacts = useChannelSessionFacts();
  const homeClient = useOptionalAuthenticatedClient();
  const { data: homeUser } = useCurrentUser({ client: homeClient });
  const me = useMemo(
    () => ({ uuid: homeUser?.uuid ?? null }),
    [homeUser?.uuid],
  );
  // The Slack-style intro pinned at the feed's start — public channels only;
  // the personal channel keeps the welcome empty state below.
  const isPersonal = channel ? isPersonalChannel(channel) : false;
  const spaceItems = useMemo(
    () =>
      buildChannelItems({
        dashboards: spaceCanvases,
        feedTasks: tasks,
        archivedTaskIds,
        pinnedTaskIds,
        ownedBy: isPersonal && me.uuid ? me : null,
        sessionFacts,
      }),
    [
      spaceCanvases,
      tasks,
      archivedTaskIds,
      pinnedTaskIds,
      isPersonal,
      me,
      sessionFacts,
    ],
  );
  // Marking this channel read lives in ChannelHeader (rendered by every channel
  // surface), so opening Artifacts or CONTEXT.md counts as reading it too.

  // Durable "PostHog agent" rows (CONTEXT.md being built, …). The old chat
  // feed also injected a synthetic "joined" opener here; the newest-first feed
  // drops it — the intro header already attributes the channel's creation, and
  // the opener would dangle at the bottom as the oldest entry.
  const { messages: systemMessages, isLoading: isLoadingMessages } =
    useChannelFeedMessages(channelId);
  const isLoading = isLoadingChannels || isLoadingFeed || isLoadingMessages;

  useSetHeaderContent(
    useMemo(
      () => <ChannelHeader channelId={channelId} page="home" />,
      [channelId],
    ),
    !isWork,
  );
  const { reports } = useChannelReports(
    { kind: "channel", channelId },
    DEFAULT_CHANNEL_REPORTS_FILTERS,
    { enabled: isWork },
  );

  const pullRequests = useSpacePullRequests(isWork ? tasks : NO_TASKS);
  const activityView = useSpaceActivityViewStore((s) => s.view);
  const activityTypes = useSpaceActivityViewStore((s) => s.types);
  const activityFilters = useSpaceActivityViewStore((s) => s.filters);
  const activitySort = useSpaceActivityViewStore((s) => s.sort);
  const activityGrouping = useSpaceActivityViewStore((s) => s.grouping);
  const shownView = useDeferredValue(activityView);
  const shownTypes = useDeferredValue(activityTypes);
  const shownFilters = useDeferredValue(activityFilters);
  const shownSort = useDeferredValue(activitySort);
  const shownGrouping = useDeferredValue(activityGrouping);
  const activityPending =
    shownView !== activityView ||
    shownTypes !== activityTypes ||
    shownFilters !== activityFilters ||
    shownSort !== activitySort ||
    shownGrouping !== activityGrouping;
  const activitySources = useMemo(() => {
    const seen = new Set<string>();
    for (const task of tasks) {
      if (task.origin_product) seen.add(task.origin_product);
    }
    return [...seen].sort();
  }, [tasks]);

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

  // The open thread outlives the thread view, so the feed showing itself is
  // the only signal an inherited thread is gone. Suppress it in render (an
  // effect alone would paint the sidebar for a frame first) and clear the
  // store; threads opened from this feed instance paint normally.
  const [inheritedThreadTaskId] = useState(
    () => useThreadPanelStore.getState().openByChannel[channelId] ?? null,
  );
  useEffect(() => {
    if (inheritedThreadTaskId) {
      useThreadPanelStore.getState().closeThread(channelId);
    }
  }, [channelId, inheritedThreadTaskId]);

  const handleSuggestionSelect = useCallback(
    (prompt: string, mode?: string) => {
      composerRef.current?.applySuggestion(prompt, mode);
    },
    [],
  );

  const invalidateFeed = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: channelFeedQueryKey(channelId),
    });
  }, [queryClient, channelId]);

  // Slack behavior: submitting keeps you in the channel; the new card appears
  // in the feed and updates live. Filing into the channel keeps the Artifacts /
  // Recents tabs working.
  const onTaskCreated = useCallback(
    (task: Task) => {
      queryClient.setQueryData(taskDetailQuery(task.id).queryKey, task);
      // Splice the real card straight into the feed so it appears now rather
      // than after the invalidate refetch (or the next 5s poll) lands. Seed a
      // fresh list when the feed cache hasn't populated yet — insertTaskDedup
      // no-ops on an undefined cache, which would otherwise drop the card.
      queryClient.setQueryData<Task[]>(channelFeedQueryKey(channelId), (old) =>
        old ? insertTaskDedup(old, task) : [task],
      );
      invalidateFeed();
      void fileTask(channelId, task.id)
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
          toast.error(
            `Couldn't file task to ${spacesLayout ? "space" : "channel"}`,
            {
              description:
                error instanceof Error ? error.message : String(error),
            },
          );
        });
    },
    [channelId, fileTask, invalidateFeed, queryClient, spacesLayout],
  );

  const handleOpenFull = useCallback(
    (taskId: string) => {
      void navigate({
        to: "/spaces/$channelId/tasks/$taskId",
        params: { channelId, taskId },
      });
    },
    [channelId, navigate],
  );
  const handleOpenTask = useCallback(
    (task: Task) => handleOpenFull(task.id),
    [handleOpenFull],
  );

  // Under the spaces chrome there is no thread dock to peek into, so the feed
  // opens the session itself and the right panel carries what the dock used to
  // — including a chip's tab, which lands on the matching panel side there.
  const handleOpenThread = useCallback(
    (task: Task, tab?: ThreadPanelTab) => {
      if (spacesLayout && !isWork) {
        if (tab) openRightPanelSide(tab, task.id);
        handleOpenFull(task.id);
        return;
      }
      openThread(channelId, task.id, tab ? { tab } : undefined);
    },
    [channelId, openThread, spacesLayout, isWork, handleOpenFull],
  );
  const handleOpenReport = useCallback(
    (reportId: string) => navigateToChannelReportDetail(channelId, reportId),
    [channelId],
  );

  const showsThreadDock =
    (!spacesLayout || isWork) &&
    !!threadTaskId &&
    threadTaskId !== inheritedThreadTaskId;
  const threadTask = threadTaskId
    ? tasks.find((t) => t.id === threadTaskId)
    : undefined;

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
  const introDismissed = useChannelIntroStore(
    (s) => !!s.dismissedByChannel[channelId],
  );
  const dismissIntro = useChannelIntroStore((s) => s.dismissIntro);
  const intro =
    !isWork && !isPersonal && !introDismissed && channelName && channel ? (
      <ChannelIntro
        channel={channel}
        channelName={channelName}
        contextMdState={contextMdState}
        onCreateContextMd={() => setContextMdDialogOpen(true)}
        onDismiss={() => dismissIntro(channelId)}
      />
    ) : undefined;

  const emptyState = (
    <div
      className={cn(
        "flex w-full flex-col gap-6",
        isWork
          ? "max-w-[900px] pt-8 pb-10"
          : "mx-auto min-h-full max-w-[680px] justify-center px-4 py-10",
      )}
    >
      <div
        className={cn(
          "flex flex-col gap-2",
          isWork ? "items-start" : "items-center text-center",
        )}
      >
        <h2
          className={cn(
            "text-foreground",
            isWork ? "font-semibold text-lg" : "font-bold text-2xl",
          )}
        >
          {isPersonal
            ? "Welcome to your own personal context"
            : channelName
              ? `Welcome to ${channelName}`
              : "Welcome"}
        </h2>
        <p
          className={cn(
            "text-muted-foreground",
            isWork ? "max-w-[560px] text-[13px]" : "text-sm",
          )}
        >
          Contexts are for areas of work. Context.md is self-updating, so start
          some work and the context file will update itself.
        </p>
      </div>
      <div className="flex flex-col gap-2">
        <p className="px-1 font-medium text-[13px] text-muted-foreground">
          Suggestions
        </p>
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
          composer={
            <ChannelHomeComposer
              ref={composerRef}
              channelId={channelId}
              channelName={channelName}
              channelContext={channelContext}
              channelRepositories={channel?.repositories}
              channelGithubIntegration={channel?.github_integration}
              onTaskCreated={onTaskCreated}
              onPendingStart={addPending}
              onPendingEnd={removePending}
            />
          }
          onOpenTask={handleOpenTask}
          onOpenThread={handleOpenThread}
          compact={isWork}
          rowStyle={isWork ? shownView : undefined}
          rebuilding={activityPending}
          onClearFilters={
            isWork
              ? () =>
                  useSpaceActivityViewStore
                    .getState()
                    .setFilters(DEFAULT_CHANNEL_ITEM_FILTERS)
              : undefined
          }
          canvases={isWork ? spaceCanvases : undefined}
          pullRequests={isWork ? pullRequests : undefined}
          types={isWork ? shownTypes : undefined}
          spaceItems={isWork ? spaceItems : undefined}
          me={isWork ? me : undefined}
          controls={
            isWork ? (
              <div className="mb-1 flex w-full items-center justify-end">
                <SpaceActivityControls sources={activitySources} />
              </div>
            ) : undefined
          }
          filters={isWork ? shownFilters : undefined}
          sort={isWork ? shownSort : undefined}
          grouping={isWork ? shownGrouping : undefined}
          reports={isWork ? reports : undefined}
          onOpenReport={isWork ? handleOpenReport : undefined}
          showKindFilter={!isWork}
        />
      </div>

      {showsThreadDock ? (
        <ThreadSidebar
          taskId={threadTaskId}
          channelId={channelId}
          task={threadTask}
          onClose={() => closeThread(channelId)}
          onOpenFull={() => handleOpenFull(threadTaskId)}
        />
      ) : null}

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
