import {
  ArrowSquareOutIcon,
  CaretRightIcon,
  DotsThreeIcon,
  PaperPlaneRightIcon,
  RobotIcon,
  TrashIcon,
  XIcon,
} from "@phosphor-icons/react";
import {
  buildThreadTimeline,
  deriveThreadAgentStatus,
  hasAgentMention,
  shouldSuspendThreadSession,
  type ThreadAgentStatus,
  type ThreadArtifact,
  type ThreadTimelineRow,
} from "@posthog/core/canvas/threadTimeline";
import {
  getPrVisualConfig,
  parsePrNumber,
} from "@posthog/core/git-interaction/prStatus";
import {
  Avatar,
  AvatarFallback,
  Badge,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  InputGroupAddon,
  InputGroupButton,
  Spinner,
  ThreadItem,
  ThreadItemAction,
  ThreadItemActions,
  ThreadItemAuthor,
  ThreadItemBody,
  ThreadItemContent,
  ThreadItemGroup,
  ThreadItemGutter,
  ThreadItemHeader,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type {
  Task,
  TaskThreadMessage,
  UserBasic,
} from "@posthog/shared/domain-types";
import { isTerminalStatus } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { TaskCard } from "@posthog/ui/features/canvas/components/ChannelFeedView";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import { MentionComposer } from "@posthog/ui/features/canvas/components/MentionComposer";
import { MentionText } from "@posthog/ui/features/canvas/components/MentionText";
import { ThreadTimestamp } from "@posthog/ui/features/canvas/components/ThreadTimestamp";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import {
  useDeleteTaskThreadMessage,
  usePostTaskThreadMessage,
  usePostTaskThreadMessageToAgent,
  useSendTaskThreadMessageToAgent,
  useTaskThread,
} from "@posthog/ui/features/canvas/hooks/useTaskThread";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { getPrVisualIcon } from "@posthog/ui/features/git-interaction/prIcon";
import { usePrDetails } from "@posthog/ui/features/git-interaction/usePrDetails";
import { useSessionConnection } from "@posthog/ui/features/sessions/hooks/useSessionConnection";
import { useSessionViewState } from "@posthog/ui/features/sessions/hooks/useSessionViewState";
import { usePendingPermissionsForTask } from "@posthog/ui/features/sessions/sessionStore";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { parseShareLink } from "@posthog/ui/utils/posthogLinks";
import { navigateToShareTarget } from "@posthog/ui/utils/shareLinks";
import { getPostHogUrl } from "@posthog/ui/utils/urls";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export function ThreadMessageRow({
  message,
  isTaskAuthor,
  isOwnMessage,
  currentUserEmail,
  canForward,
  onSendToAgent,
  onDelete,
}: {
  message: TaskThreadMessage;
  isTaskAuthor: boolean;
  isOwnMessage: boolean;
  currentUserEmail?: string | null;
  canForward: boolean;
  onSendToAgent: () => void;
  onDelete: () => void;
}) {
  const forwarded = !!message.forwarded_to_agent_at;
  const showMenu = (isTaskAuthor && !forwarded) || isOwnMessage;

  return (
    <ThreadItem>
      <ThreadItemGutter>
        <UserAvatar user={message.author} size="lg" className="sticky top-2" />
      </ThreadItemGutter>
      <ThreadItemContent>
        <ThreadItemHeader>
          <ThreadItemAuthor>{userDisplayName(message.author)}</ThreadItemAuthor>
          <ThreadTimestamp dateTime={message.created_at} />
        </ThreadItemHeader>
        <ThreadItemBody>
          <MentionText
            content={message.content}
            currentUserEmail={currentUserEmail}
          />
        </ThreadItemBody>
        {forwarded && (
          <Badge variant="info" className="w-fit">
            <RobotIcon size={10} />
            Sent to agent
          </Badge>
        )}
      </ThreadItemContent>
      {showMenu && (
        <ThreadItemActions>
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <ThreadItemAction label="Message actions">
                  <DotsThreeIcon size={14} />
                </ThreadItemAction>
              }
            />
            <DropdownMenuContent align="end">
              {isTaskAuthor && !forwarded && (
                <DropdownMenuItem
                  disabled={!canForward}
                  onClick={onSendToAgent}
                >
                  <PaperPlaneRightIcon size={14} />
                  Send to agent
                </DropdownMenuItem>
              )}
              {isOwnMessage && (
                <DropdownMenuItem variant="destructive" onClick={onDelete}>
                  <TrashIcon size={14} />
                  Delete message
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </ThreadItemActions>
      )}
    </ThreadItem>
  );
}

export function AgentStatusLine({ status }: { status: ThreadAgentStatus }) {
  return (
    <output
      aria-live="polite"
      className="flex items-center gap-1.5 px-3 py-1.5 text-muted-foreground text-xs"
    >
      {status.phase === "active" ? (
        <Spinner className="size-3" />
      ) : (
        <RobotIcon size={12} />
      )}
      <span>{status.label}</span>
    </output>
  );
}

function ArtifactCardButton({
  icon,
  title,
  detail,
  onOpen,
}: {
  icon: React.ReactNode;
  title: string;
  detail?: string | null;
  onOpen?: () => void;
}) {
  const body = (
    <>
      {icon}
      <span className="min-w-0 truncate font-medium">{title}</span>
      {detail && (
        <span className="shrink-0 text-muted-foreground">{detail}</span>
      )}
    </>
  );
  const cardClass =
    "flex w-fit max-w-full items-center gap-2 rounded-md border border-border bg-muted px-2 py-1.5 text-[13px]";
  if (!onOpen) {
    return <span className={cardClass}>{body}</span>;
  }
  return (
    <button
      type="button"
      onClick={onOpen}
      className={`${cardClass} text-left transition-colors hover:bg-gray-3`}
    >
      {body}
    </button>
  );
}

function parseHttpsUrl(url: string): URL | null {
  try {
    const parsedUrl = new URL(url);
    return parsedUrl.protocol === "https:" ? parsedUrl : null;
  } catch {
    return null;
  }
}

function CanvasArtifactCard({
  name,
  url,
}: {
  name: string;
  url: string | null;
}) {
  const parsedUrl = url ? parseHttpsUrl(url) : null;
  const target = parsedUrl ? parseShareLink(parsedUrl.href) : null;
  const open =
    parsedUrl && target
      ? () => {
          const currentPostHogUrl = getPostHogUrl("/");
          const currentPostHogOrigin = currentPostHogUrl
            ? parseHttpsUrl(currentPostHogUrl)?.origin
            : null;
          if (parsedUrl.origin === currentPostHogOrigin) {
            navigateToShareTarget(target);
          } else {
            openExternalUrl(parsedUrl.href);
          }
        }
      : undefined;
  return (
    <ArtifactCardButton
      icon={iconForTemplate("", { size: 14, className: "text-violet-9" })}
      title={name}
      onOpen={open}
    />
  );
}

function PrArtifactCard({ url }: { url: string }) {
  const parsedUrl = parseHttpsUrl(url);
  const safeUrl =
    parsedUrl?.origin === "https://github.com" ? parsedUrl.href : null;
  const {
    meta: { state, merged, draft },
  } = usePrDetails(safeUrl);
  const config = getPrVisualConfig(state ?? "open", merged, draft);
  const PrIcon = getPrVisualIcon(config.icon);
  const prNumber = safeUrl ? parsePrNumber(safeUrl) : null;
  return (
    <ArtifactCardButton
      icon={
        <PrIcon
          size={14}
          weight="bold"
          className="shrink-0"
          style={{ color: `var(--${config.color}-9)` }}
        />
      }
      title={prNumber ? `Pull request #${prNumber}` : "Pull request"}
      // Only show the resolved state once we have it, to avoid a flash of "Open".
      detail={state ? config.label : null}
      onOpen={safeUrl ? () => openExternalUrl(safeUrl) : undefined}
    />
  );
}

export function ThreadArtifactRow({
  artifact,
  createdAt,
}: {
  artifact: ThreadArtifact;
  createdAt: string;
}) {
  return (
    <ThreadItem>
      <ThreadItemGutter>
        <Avatar size="lg" className="sticky top-2">
          <AvatarFallback>
            <RobotIcon size={14} />
          </AvatarFallback>
        </Avatar>
      </ThreadItemGutter>
      <ThreadItemContent>
        <ThreadItemHeader>
          <ThreadItemAuthor>
            {artifact.kind === "canvas" ? "Canvas" : "Pull request"}
          </ThreadItemAuthor>
          <ThreadTimestamp dateTime={createdAt} />
        </ThreadItemHeader>
        <ThreadItemBody>
          {artifact.kind === "canvas" ? (
            <CanvasArtifactCard name={artifact.name} url={artifact.url} />
          ) : (
            <PrArtifactCard url={artifact.url} />
          )}
        </ThreadItemBody>
      </ThreadItemContent>
    </ThreadItem>
  );
}

function ThreadLoadingState() {
  return (
    <Empty className="h-full border-0">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Spinner />
        </EmptyMedia>
        <EmptyTitle>Loading thread</EmptyTitle>
      </EmptyHeader>
    </Empty>
  );
}

function ThreadHeader({
  onClose,
  onToggleCollapsed,
  onOpenFull,
}: {
  onClose?: () => void;
  onToggleCollapsed?: () => void;
  onOpenFull?: () => void;
}) {
  return (
    <div className="flex items-center gap-1 border-border border-b px-3 py-2">
      <div className="min-w-0 flex-1">
        <span className="block font-medium text-sm">Thread</span>
      </div>
      {onOpenFull && (
        <Button
          variant="default"
          size="icon-sm"
          aria-label="Open full task"
          onClick={onOpenFull}
        >
          <ArrowSquareOutIcon size={14} />
        </Button>
      )}
      {onToggleCollapsed && (
        <Button
          variant="default"
          size="icon-sm"
          aria-label="Collapse thread"
          onClick={onToggleCollapsed}
        >
          <CaretRightIcon size={14} />
        </Button>
      )}
      {onClose && (
        <Button
          variant="default"
          size="icon-sm"
          aria-label="Close thread"
          onClick={onClose}
        >
          <XIcon size={14} />
        </Button>
      )}
    </div>
  );
}

function ThreadTimeline({
  timeline,
  isReady,
  currentUserUuid,
  currentUserEmail,
  isTaskAuthor,
  canForward,
  onSendToAgent,
  onDelete,
}: {
  timeline: ThreadTimelineRow<TaskThreadMessage>[];
  isReady: boolean;
  currentUserUuid?: string;
  currentUserEmail?: string;
  isTaskAuthor: boolean;
  canForward: boolean;
  onSendToAgent: (messageId: string) => void;
  onDelete: (messageId: string) => void;
}) {
  if (!isReady) return <ThreadLoadingState />;
  if (timeline.length === 0) {
    return (
      <Empty className="h-full border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <RobotIcon size={18} />
          </EmptyMedia>
          <EmptyTitle>No messages yet</EmptyTitle>
          <EmptyDescription>
            Discuss this task with your team. Canvases and pull requests the
            agent creates show up here too; messages stay between humans unless
            the task author sends one to the agent.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <ThreadItemGroup>
      {timeline.map((row) =>
        row.kind === "human" ? (
          <ThreadMessageRow
            key={row.message.id}
            message={row.message}
            isTaskAuthor={isTaskAuthor}
            isOwnMessage={
              !!currentUserUuid && currentUserUuid === row.message.author?.uuid
            }
            currentUserEmail={currentUserEmail}
            canForward={canForward}
            onSendToAgent={() => onSendToAgent(row.message.id)}
            onDelete={() => onDelete(row.message.id)}
          />
        ) : (
          <ThreadArtifactRow
            key={row.message.id}
            artifact={row.artifact}
            createdAt={row.message.created_at}
          />
        ),
      )}
    </ThreadItemGroup>
  );
}

function ThreadReplyComposer({
  draft,
  onDraftChange,
  onSubmit,
  members,
  allowAgentMention,
  onMentionInsert,
  disabled,
}: {
  draft: string;
  onDraftChange: (value: string) => void;
  onSubmit: () => void;
  members: UserBasic[];
  allowAgentMention: boolean;
  onMentionInsert: (member: UserBasic) => void;
  disabled: boolean;
}) {
  return (
    <div className="border-border border-t p-2">
      <MentionComposer
        value={draft}
        onValueChange={onDraftChange}
        onSubmit={onSubmit}
        members={members}
        allowAgentMention={allowAgentMention}
        onMentionInsert={onMentionInsert}
        placeholder="Reply in thread… @agent sends to the agent"
        rows={2}
        inputClassName="max-h-40 text-[13px]"
      >
        <InputGroupAddon align="block-end" className="p-1">
          <span className="ml-auto flex items-center gap-1">
            <InputGroupButton
              variant="primary"
              size="icon-sm"
              aria-label="Send"
              disabled={disabled}
              onClick={onSubmit}
            >
              <PaperPlaneRightIcon size={14} />
            </InputGroupButton>
          </span>
        </InputGroupAddon>
      </MentionComposer>
    </div>
  );
}

function ThreadConversation({
  task,
  channelId,
  onClose,
  onToggleCollapsed,
  onOpenFull,
  showTaskSummary,
}: {
  task: Task;
  channelId: string;
  onClose?: () => void;
  onToggleCollapsed?: () => void;
  onOpenFull?: () => void;
  showTaskSummary: boolean;
}) {
  const taskId = task.id;
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });

  const { messages, isLoading } = useTaskThread(taskId);
  const { postMessage, isPosting } = usePostTaskThreadMessage(taskId);
  const { postMessageToAgent, isPostingToAgent } =
    usePostTaskThreadMessageToAgent(taskId);
  const { deleteMessage } = useDeleteTaskThreadMessage(taskId);
  const { sendToAgent, isSending } = useSendTaskThreadMessageToAgent(taskId);
  const isSendingToAgent = isPostingToAgent || isSending;
  const { members } = useOrgMembers();

  const {
    session,
    repoPath,
    isCloud,
    events,
    cloudStatus,
    isPromptPending,
    isInitializing,
    hasError,
    errorTitle,
  } = useSessionViewState(taskId, task);
  useSessionConnection({
    taskId,
    task,
    session,
    repoPath,
    isCloud,
    isSuspended: shouldSuspendThreadSession({
      isCloud,
      hasRun: Boolean(task.latest_run?.id),
      hasSession: Boolean(session),
    }),
  });
  const pendingPermissions = usePendingPermissionsForTask(taskId);

  const agentStatus = useMemo(
    () =>
      deriveThreadAgentStatus({
        hasActivity: events.length > 0 || !!task.latest_run,
        hasError,
        cloudStatus,
        errorTitle,
        pendingPermissionCount: pendingPermissions.size,
        isPromptPending,
        isInitializing,
      }),
    [
      events.length,
      task.latest_run,
      hasError,
      cloudStatus,
      errorTitle,
      pendingPermissions.size,
      isPromptPending,
      isInitializing,
    ],
  );

  const timeline = useMemo(() => buildThreadTimeline(messages), [messages]);

  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const handleMentionInsert = useCallback(
    (member: UserBasic) => {
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "mention_member",
        surface: "thread_panel",
        task_id: taskId,
        mentioned_user_id: member.uuid,
      });
    },
    [taskId],
  );

  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll when rendered thread content changes
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [timeline, agentStatus?.phase]);

  const isTaskAuthor =
    !!currentUser?.uuid && currentUser.uuid === task.created_by?.uuid;
  const canForward =
    !!task.latest_run &&
    !isTerminalStatus(task.latest_run.status) &&
    !isSendingToAgent;

  const submit = async () => {
    const content = draft.trim();
    if (!content || isPosting || isSendingToAgent) return;
    const sendToAgentRequested = hasAgentMention(content);
    if (sendToAgentRequested && (!isTaskAuthor || !canForward)) {
      toast.error("Couldn't send to agent", {
        description:
          "Only the task author can @agent while the task has an active run.",
      });
      return;
    }
    setDraft("");
    try {
      if (sendToAgentRequested) {
        const { sendError } = await postMessageToAgent(content);
        if (sendError) {
          toast.error("Message posted, but couldn't send it to the agent", {
            description:
              sendError instanceof Error
                ? sendError.message
                : String(sendError),
          });
        }
      } else {
        await postMessage(content);
      }
    } catch (error) {
      setDraft(content);
      toast.error("Couldn't post message", {
        description: error instanceof Error ? error.message : String(error),
      });
    }
  };

  const handleSendToAgent = (messageId: string) => {
    sendToAgent(messageId).catch((error: unknown) => {
      toast.error("Couldn't send message to agent", {
        description: error instanceof Error ? error.message : String(error),
      });
    });
  };

  const handleDelete = (messageId: string) => {
    deleteMessage(messageId).catch((error: unknown) => {
      toast.error("Couldn't delete message", {
        description: error instanceof Error ? error.message : String(error),
      });
    });
  };

  const isReady = !isInitializing && !isLoading;

  return (
    <div className="flex h-full min-w-0 flex-col bg-gray-1">
      <ThreadHeader
        onOpenFull={onOpenFull}
        onToggleCollapsed={onToggleCollapsed}
        onClose={onClose}
      />

      {showTaskSummary && (
        <div className="z-10 px-2">
          <TaskCard task={task} channelId={channelId} inThread />
        </div>
      )}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <ThreadTimeline
          timeline={timeline}
          isReady={isReady}
          currentUserUuid={currentUser?.uuid}
          currentUserEmail={currentUser?.email}
          isTaskAuthor={isTaskAuthor}
          canForward={canForward}
          onSendToAgent={handleSendToAgent}
          onDelete={handleDelete}
        />
      </div>

      {agentStatus && <AgentStatusLine status={agentStatus} />}

      <ThreadReplyComposer
        draft={draft}
        onDraftChange={setDraft}
        onSubmit={submit}
        members={members}
        allowAgentMention={isTaskAuthor && canForward}
        onMentionInsert={handleMentionInsert}
        disabled={!draft.trim() || isPosting || isSendingToAgent}
      />
    </div>
  );
}

export function ThreadPanel({
  taskId,
  channelId,
  task: taskProp,
  onClose,
  collapsed,
  onToggleCollapsed,
  onOpenFull,
  showTaskSummary = true,
}: {
  taskId: string;
  channelId: string;
  task?: Task;
  onClose?: () => void;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  onOpenFull?: () => void;
  showTaskSummary?: boolean;
}) {
  const { data: fetchedTask } = useQuery({
    ...taskDetailQuery(taskId),
    enabled: !taskProp && !collapsed,
  });
  const task = taskProp ?? fetchedTask;

  if (collapsed) {
    return (
      <div className="flex h-full w-9 flex-col items-center border-border border-l bg-gray-1 py-2">
        <Button
          variant="default"
          size="icon-sm"
          aria-label="Expand thread"
          onClick={onToggleCollapsed}
        >
          <CaretRightIcon size={14} className="rotate-180" />
        </Button>
      </div>
    );
  }

  if (!task) {
    return <ThreadLoadingState />;
  }

  return (
    <ThreadConversation
      task={task}
      channelId={channelId}
      onClose={onClose}
      onToggleCollapsed={onToggleCollapsed}
      onOpenFull={onOpenFull}
      showTaskSummary={showTaskSummary}
    />
  );
}
