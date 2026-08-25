import {
  ChatCircleIcon,
  CheckIcon,
  ChecksIcon,
  LinkIcon,
  QuestionIcon,
} from "@phosphor-icons/react";
import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { Avatar, AvatarFallback, Badge, Button, cn } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { UserBasic } from "@posthog/shared/domain-types";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import {
  type AgentActivityIconKind,
  activityPresentation,
} from "@posthog/ui/features/canvas/components/activityPresentation";
import { MentionText } from "@posthog/ui/features/canvas/components/MentionText";
import { copyChannelLink } from "@posthog/ui/features/canvas/utils/copyChannelLink";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { track } from "@posthog/ui/shell/analytics";
import type { ReactElement } from "react";

function AgentActivityIcon({
  kind,
  className,
}: {
  kind: AgentActivityIconKind;
  className?: string;
}): ReactElement {
  switch (kind) {
    case "check":
      return <ChecksIcon size={13} weight="bold" className={className} />;
    case "question":
      return <QuestionIcon size={12} weight="bold" className={className} />;
    case "chat":
      return <ChatCircleIcon size={13} weight="bold" className={className} />;
    default: {
      const exhaustiveIconKind: never = kind;
      return exhaustiveIconKind;
    }
  }
}

interface ActivityRowProps {
  item: TaskActivityItem;
  onMarkRead: (item: TaskActivityItem) => void;
  currentUser?: UserBasic | null;
  blockedTaskIds: ReadonlySet<string>;
  surface?: "activity" | "activity_panel";
  onActivate: (item: TaskActivityItem) => void;
  isSelected?: boolean;
  compact?: boolean;
}

export function ActivityRow({
  item,
  onMarkRead,
  currentUser,
  blockedTaskIds,
  surface = "activity",
  onActivate,
  isSelected = false,
  compact = false,
}: ActivityRowProps): ReactElement {
  const presentation = activityPresentation(item, currentUser?.email);
  const channelId = item.channelId;
  // The event records a past prompt; only the live session says whether it
  // still needs a reply after the row was created.
  const awaitsReply =
    item.activityKind === "awaiting_input" && blockedTaskIds.has(item.taskId);
  const agentIconClassName = awaitsReply ? "text-(--blue-11)" : undefined;
  const agentIconWrapperClassName =
    item.isUnread && !awaitsReply
      ? "bg-primary text-primary-foreground"
      : undefined;
  const openTask = (): void => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "open_task",
      surface,
      channel_id: channelId ?? undefined,
      task_id: item.taskId,
    });
    onMarkRead(item);
    if (item.commentId && item.commentTarget) {
      useCommentNavigationStore
        .getState()
        .requestCommentFocus(item.taskId, item.commentTarget, item.commentId);
    }
    onActivate(item);
  };

  return (
    <div className="group relative">
      <Button
        type="button"
        onClick={openTask}
        aria-label={`${item.taskTitle} ${presentation.metadata}${presentation.spaceLabel ? ` ${presentation.spaceLabel}` : ""}`}
        left
        className={cn(
          "h-auto w-full items-start text-left",
          compact ? "py-1.5" : "py-2",
          compact && item.isUnread && "pr-8",
          isSelected && "bg-fill-selected",
        )}
      >
        <span className="mt-0.5 shrink-0">
          {presentation.agentIcon ? (
            <Avatar
              size="xs"
              className={cn(agentIconWrapperClassName, compact && "size-4")}
            >
              <AvatarFallback>
                <AgentActivityIcon
                  kind={presentation.agentIcon}
                  className={agentIconClassName}
                />
              </AvatarFallback>
            </Avatar>
          ) : (
            <span className="mt-1 flex shrink-0">
              <UserAvatar
                user={item.author ?? currentUser}
                size="xs"
                className={compact ? "size-4" : undefined}
              />
            </span>
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span
              className={`truncate text-[13px] ${item.isUnread ? "font-semibold" : "font-medium"}`}
            >
              {item.taskTitle}
            </span>
            {item.isUnread && !compact && <Badge variant="info">New</Badge>}
          </span>
          <span className="flex min-w-0 items-center gap-1 text-muted-foreground text-xxs">
            <span className="truncate">{presentation.metadata}</span>
            {presentation.spaceLabel && (
              <Badge
                variant="default"
                className="min-w-0 shrink rounded-xs bg-muted/70 p-0"
                title={presentation.spaceLabel}
              >
                <span className="truncate">{presentation.spaceLabel}</span>
              </Badge>
            )}
          </span>
          {item.snippet && !compact && (
            <MentionText
              content={item.snippet}
              currentUserEmail={currentUser?.email}
              className="mt-1 block whitespace-pre-wrap break-words text-xs"
            />
          )}
        </span>
      </Button>
      {item.isUnread && (
        <Button
          variant="default"
          size="icon-xs"
          aria-label="Mark as read"
          title="Mark as read"
          className={`absolute opacity-0 transition-opacity group-hover:opacity-100 ${compact ? "top-2 right-2" : `top-2 ${channelId ? "right-9" : "right-2"}`}`}
          onClick={() => onMarkRead(item)}
        >
          <CheckIcon size={14} />
        </Button>
      )}
      {channelId && !compact && (
        <Button
          variant="default"
          size="icon-xs"
          aria-label="Copy thread link"
          className="absolute top-2 right-2 opacity-0 transition-opacity group-hover:opacity-100"
          onClick={() =>
            void copyChannelLink(channelId, "activity", item.taskId)
          }
        >
          <LinkIcon size={14} />
        </Button>
      )}
    </div>
  );
}
