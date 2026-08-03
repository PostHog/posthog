import {
  ArrowSquareOutIcon,
  CaretRightIcon,
  DotsThreeIcon,
  PaperPlaneRightIcon,
  RobotIcon,
  TrashIcon,
  XIcon,
} from "@phosphor-icons/react";
import type {
  ThreadAgentStatus,
  ThreadArtifact,
  ThreadTimelineRow,
} from "@posthog/core/canvas/threadTimeline";
import {
  Avatar,
  AvatarFallback,
  Badge,
  Button,
  cn,
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
import type {
  Task,
  TaskThreadMessage,
  UserBasic,
} from "@posthog/shared/domain-types";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { TaskCard } from "@posthog/ui/features/canvas/components/ChannelFeedView";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import { MentionComposer } from "@posthog/ui/features/canvas/components/MentionComposer";
import { MentionText } from "@posthog/ui/features/canvas/components/MentionText";
import { ThreadTimestamp } from "@posthog/ui/features/canvas/components/ThreadTimestamp";
import { useThreadConversation } from "@posthog/ui/features/canvas/hooks/useThreadConversation";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { openPrInReview } from "@posthog/ui/features/code-review/openPrInReview";
import { usePrArtifact } from "@posthog/ui/features/git-interaction/usePrArtifact";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { parseHttpsUrl, parseShareLink } from "@posthog/ui/utils/posthogLinks";
import { navigateToShareTarget } from "@posthog/ui/utils/shareLinks";
import { getPostHogUrl } from "@posthog/ui/utils/urls";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

export function ThreadMessageRow({
  message,
  isTaskAuthor,
  isOwnMessage,
  currentUserEmail,
  canForward,
  preview,
  onSendToAgent,
  onDelete,
}: {
  message: TaskThreadMessage;
  isTaskAuthor: boolean;
  isOwnMessage: boolean;
  currentUserEmail?: string | null;
  canForward: boolean;
  /** Timeline rows preserve authored whitespace while showing the full message. */
  preview?: boolean;
  onSendToAgent: () => void;
  onDelete: () => void;
}) {
  const forwarded = !!message.forwarded_to_agent_at;
  const showMenu = (isTaskAuthor && !forwarded) || isOwnMessage;

  return (
    <ThreadItem>
      <ThreadItemGutter className="justify-center">
        <UserAvatar user={message.author} size="sm" className="sticky top-2" />
      </ThreadItemGutter>
      <ThreadItemContent>
        <ThreadItemHeader>
          <ThreadItemAuthor className="text-[13px]">
            {userDisplayName(message.author)}
          </ThreadItemAuthor>
          <ThreadTimestamp dateTime={message.created_at} />
        </ThreadItemHeader>
        <ThreadItemBody
          className={cn(
            "mt-1.5 text-[13px]",
            preview && "whitespace-pre-wrap break-words",
          )}
        >
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
  onOpenExternal,
}: {
  icon: React.ReactNode;
  title: string;
  detail?: string | null;
  onOpen?: () => void;
  /** Renders a trailing button that leaves the app instead of opening the
   *  artifact in place. Absent when there is nowhere safe to send the user. */
  onOpenExternal?: () => void;
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
  const innerClass = "flex min-w-0 items-center gap-2 px-2 py-1.5";
  return (
    // overflow-hidden so each half's hover fill is clipped to the card's radius.
    <div className="flex w-fit max-w-full items-center overflow-hidden rounded-md border border-border bg-muted text-[13px]">
      {onOpen ? (
        <button
          type="button"
          onClick={onOpen}
          className={cn(
            innerClass,
            "text-left transition-colors hover:bg-gray-3",
          )}
        >
          {body}
        </button>
      ) : (
        <span className={innerClass}>{body}</span>
      )}
      {onOpenExternal && (
        <button
          type="button"
          onClick={onOpenExternal}
          aria-label={`Open ${title} externally`}
          className="flex shrink-0 items-center self-stretch border-border border-l px-1.5 text-muted-foreground transition-colors hover:bg-gray-3 hover:text-foreground"
        >
          <ArrowSquareOutIcon size={12} />
        </button>
      )}
    </div>
  );
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

function PrArtifactCard({
  url,
  openInPlaceTaskId,
}: {
  url: string;
  openInPlaceTaskId?: string;
}) {
  const { safeUrl, title, stateLabel, Icon, iconColor } = usePrArtifact(url);
  return (
    <ArtifactCardButton
      icon={
        <Icon
          size={14}
          weight="bold"
          className="shrink-0"
          style={{ color: iconColor }}
        />
      }
      title={title}
      detail={stateLabel}
      onOpen={
        safeUrl
          ? () =>
              openInPlaceTaskId
                ? openPrInReview(openInPlaceTaskId, safeUrl)
                : openExternalUrl(safeUrl)
          : undefined
      }
      onOpenExternal={safeUrl ? () => openExternalUrl(safeUrl) : undefined}
    />
  );
}

export function ThreadArtifactRow({
  artifact,
  createdAt,
  openInPlaceTaskId,
}: {
  artifact: ThreadArtifact;
  createdAt: string;
  /** Task whose review pane is mounted alongside; absent means open externally. */
  openInPlaceTaskId?: string;
}) {
  return (
    <ThreadItem>
      <ThreadItemGutter className="justify-center">
        <Avatar size="sm" className="sticky top-2">
          <AvatarFallback>
            <RobotIcon size={12} />
          </AvatarFallback>
        </Avatar>
      </ThreadItemGutter>
      <ThreadItemContent>
        <ThreadItemHeader>
          <ThreadItemAuthor className="text-[13px]">
            {artifact.kind === "canvas" ? "Canvas" : "Pull request"}
          </ThreadItemAuthor>
          <ThreadTimestamp dateTime={createdAt} />
        </ThreadItemHeader>
        <ThreadItemBody className="mt-1.5 text-[13px]">
          {artifact.kind === "canvas" ? (
            <CanvasArtifactCard name={artifact.name} url={artifact.url} />
          ) : (
            <PrArtifactCard
              url={artifact.url}
              openInPlaceTaskId={openInPlaceTaskId}
            />
          )}
        </ThreadItemBody>
      </ThreadItemContent>
    </ThreadItem>
  );
}

export function ThreadLoadingState() {
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

/** The panel's title row and window controls. ActivityPanel has its own header
 *  (the tabs are its title row), so this is the legacy panel's alone. */
function ThreadPanelHeader({
  title,
  onClose,
  onToggleCollapsed,
  onOpenFull,
}: {
  title: string;
  onClose?: () => void;
  onToggleCollapsed?: () => void;
  onOpenFull?: () => void;
}) {
  return (
    <div className="flex items-center gap-1 border-border border-b px-3 py-2">
      <div className="min-w-0 flex-1">
        <span className="block font-medium text-sm">{title}</span>
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
          aria-label={`Collapse ${title.toLowerCase()}`}
          onClick={onToggleCollapsed}
        >
          <CaretRightIcon size={14} />
        </Button>
      )}
      {onClose && (
        <Button
          variant="default"
          size="icon-sm"
          aria-label={`Close ${title.toLowerCase()}`}
          onClick={onClose}
        >
          <XIcon size={14} />
        </Button>
      )}
    </div>
  );
}

export function ThreadTimeline({
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

export function ThreadReplyComposer({
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
  const conversation = useThreadConversation(task, {
    surface: "thread_panel",
  });
  const {
    timeline,
    agentStatus,
    isReady,
    members,
    currentUser,
    isTaskAuthor,
    canForward,
    draft,
    setDraft,
    isSubmitDisabled,
    submit,
    sendMessageToAgent,
    deleteMessage,
    onMentionInsert,
  } = conversation;

  const scrollRef = useRef<HTMLDivElement>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll when rendered thread content changes
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [timeline, agentStatus?.phase]);

  return (
    <div className="flex h-full min-w-0 flex-col bg-gray-1">
      <ThreadPanelHeader
        title="Thread"
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
          onSendToAgent={sendMessageToAgent}
          onDelete={deleteMessage}
        />
      </div>

      {agentStatus && <AgentStatusLine status={agentStatus} />}

      <ThreadReplyComposer
        draft={draft}
        onDraftChange={setDraft}
        onSubmit={submit}
        members={members}
        allowAgentMention={isTaskAuthor && canForward}
        onMentionInsert={onMentionInsert}
        disabled={isSubmitDisabled}
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
