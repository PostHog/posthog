import {
  ChatCircleIcon,
  CheckIcon,
  ChecksIcon,
  LinkIcon,
  QuestionIcon,
} from "@phosphor-icons/react";
import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { Avatar, AvatarFallback, Badge, Button } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { UserBasic } from "@posthog/shared/domain-types";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import {
  type AgentActivityIconKind,
  activityPresentation,
} from "@posthog/ui/features/canvas/components/activityPresentation";
import { MentionText } from "@posthog/ui/features/canvas/components/MentionText";
import {
  TaskRowDropdownMenu,
  type TaskRowMenuProps,
} from "@posthog/ui/features/canvas/components/TaskRowMenu";
import { copyChannelLink } from "@posthog/ui/features/canvas/utils/copyChannelLink";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { RailListItem } from "@posthog/ui/features/sidebar/components/RailListItem";
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
  /** The row's task actions, built once for the feed by `useActivityTaskMenu`. */
  menu: TaskRowMenuProps;
  onMarkRead: (item: TaskActivityItem) => void;
  currentUser?: UserBasic | null;
  blockedTaskIds: ReadonlySet<string>;
  surface?: "activity" | "activity_panel";
  onActivate: (item: TaskActivityItem) => void;
  isSelected?: boolean;
  compact?: boolean;
  asOption?: boolean;
  optionValue?: string;
}

export function ActivityRow({
  item,
  menu,
  onMarkRead,
  currentUser,
  blockedTaskIds,
  surface = "activity",
  onActivate,
  isSelected = false,
  compact = false,
  asOption = false,
  optionValue,
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
  const canCopyLink = channelId !== null && !compact;
  const actionCount = 1 + (item.isUnread ? 1 : 0) + (canCopyLink ? 1 : 0);
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
    <RailListItem
      leading={
        presentation.agentIcon ? (
          <Avatar size="xs" className={agentIconWrapperClassName}>
            <AvatarFallback>
              <AgentActivityIcon
                kind={presentation.agentIcon}
                className={agentIconClassName}
              />
            </AvatarFallback>
          </Avatar>
        ) : (
          <UserAvatar user={item.author ?? currentUser} size="xs" />
        )
      }
      title={item.taskTitle}
      emphasized={item.isUnread}
      titleAccessory={
        item.isUnread && !compact && <Badge variant="info">New</Badge>
      }
      meta={
        <>
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
        </>
      }
      detail={
        presentation.lastTurn ? (
          <>
            <span className="font-medium text-foreground/80">
              {presentation.lastTurn.speaker}:
            </span>{" "}
            <MentionText
              content={presentation.lastTurn.text}
              currentUserEmail={currentUser?.email}
              className="inline"
            />
          </>
        ) : undefined
      }
      clampDetail={compact}
      actions={
        <>
          {item.isUnread && (
            <Button
              variant="default"
              size="icon-xs"
              aria-label="Mark as read"
              title="Mark as read"
              onClick={() => onMarkRead(item)}
            >
              <CheckIcon size={14} />
            </Button>
          )}
          {canCopyLink && (
            <Button
              variant="default"
              size="icon-xs"
              aria-label="Copy thread link"
              onClick={() =>
                void copyChannelLink(channelId, "activity", item.taskId)
              }
            >
              <LinkIcon size={14} />
            </Button>
          )}
          <TaskRowDropdownMenu menu={menu} />
        </>
      }
      actionCount={actionCount}
      asOption={asOption}
      optionValue={optionValue}
      compact={compact}
      isSelected={isSelected}
      onClick={openTask}
      aria-label={`${item.taskTitle} ${presentation.metadata}${presentation.spaceLabel ? ` ${presentation.spaceLabel}` : ""}`}
    />
  );
}
