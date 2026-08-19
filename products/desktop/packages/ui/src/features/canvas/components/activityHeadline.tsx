import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { Text } from "@radix-ui/themes";
import type { ReactNode } from "react";

function ChannelSuffix({
  channelName,
}: {
  channelName: string | null;
}): ReactNode {
  if (!channelName) return null;
  const label =
    channelName === "personal" ? "your personal space" : `#${channelName}`;
  return (
    <>
      {" in "}
      <Text as="span" size="1" weight="medium">
        {label}
      </Text>
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

export function activityHeadline(
  item: TaskActivityItem,
  currentUserEmail?: string | null,
): ReactNode {
  if (item.targetScope === "desktop_canvas") {
    return (
      <>
        A report canvas is ready
        <ChannelSuffix channelName={item.channelName} />
      </>
    );
  }
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
          <Text as="span" size="1" weight="medium">
            {userDisplayName(item.author)}
          </Text>{" "}
          mentioned you
          <ChannelSuffix channelName={item.channelName} />
        </>
      );
    case "thread_reply":
      return (
        <>
          <Text as="span" size="1" weight="medium">
            {userDisplayName(item.author)}
          </Text>{" "}
          replied to a thread you participated in
          <ChannelSuffix channelName={item.channelName} />
        </>
      );
    case "owned_item_comment":
      return (
        <>
          <Text as="span" size="1" weight="medium">
            {userDisplayName(item.author)}
          </Text>{" "}
          commented on your {ownedItemName(item)}
          <ChannelSuffix channelName={item.channelName} />
        </>
      );
    default:
      return "You created this task";
  }
}
