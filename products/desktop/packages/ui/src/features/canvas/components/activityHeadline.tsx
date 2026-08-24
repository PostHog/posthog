import { channelDisplayReference } from "@posthog/core/canvas/channelName";
import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import type { ReactNode } from "react";

function ChannelSuffix({ channelName }: { channelName: string | null }) {
  if (!channelName) return null;
  return (
    <>
      {" in "}
      <span className="font-medium text-xs">
        {channelDisplayReference(channelName)}
      </span>
    </>
  );
}

function ownedItemName(item: TaskActivityItem): string {
  switch (item.commentTarget?.scope) {
    case "desktop_canvas":
      return "canvas";
    case "task_artifact":
      return "artifact";
    default:
      return "task";
  }
}

/** The lead line describing what happened, chosen by the row's activity kind. */
export function activityHeadline(
  item: TaskActivityItem,
  currentUserEmail?: string | null,
): ReactNode {
  switch (item.activityKind) {
    case "awaiting_input":
      return (
        <>
          The agent is waiting for your reply
          <ChannelSuffix channelName={item.channelName} />
        </>
      );
    case "completed":
      return (
        <>
          The agent completed this task
          <ChannelSuffix channelName={item.channelName} />
        </>
      );
    case "message":
      if (!item.author) {
        return (
          <>
            The agent replied
            <ChannelSuffix channelName={item.channelName} />
          </>
        );
      }
      return (
        <>
          {item.author.email === currentUserEmail
            ? "You replied"
            : `${userDisplayName(item.author)} replied`}
          <ChannelSuffix channelName={item.channelName} />
        </>
      );
    case "mention":
      return (
        <>
          <span className="font-medium text-xs">
            {userDisplayName(item.author)}
          </span>{" "}
          mentioned you
          <ChannelSuffix channelName={item.channelName} />
        </>
      );
    case "thread_reply":
      return (
        <>
          <span className="font-medium text-xs">
            {userDisplayName(item.author)}
          </span>{" "}
          replied to a thread you participated in
          <ChannelSuffix channelName={item.channelName} />
        </>
      );
    case "owned_item_comment":
      return (
        <>
          <span className="font-medium text-xs">
            {userDisplayName(item.author)}
          </span>{" "}
          commented on your {ownedItemName(item)}
          <ChannelSuffix channelName={item.channelName} />
        </>
      );
    default:
      return "You created this task";
  }
}
