import { shouldPollChannelFeed } from "@posthog/core/canvas/channelFeed";
import type {
  ChannelFeedMessage,
  UserBasic,
} from "@posthog/shared/domain-types";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMemo } from "react";

// Multiplayer, like the task feed: poll so a teammate's announcement appears
// without a dedicated push channel.
const CHANNEL_FEED_MESSAGES_POLL_INTERVAL_MS = 5_000;

// A channel-feed system message flattened to what the feed renders.
export interface ChannelFeedSystemMessage {
  id: string;
  /** ISO; interleaved with task cards in the feed. */
  createdAt: string;
  text: string;
  /** When set, the row renders as this user (avatar + name) instead of the
   * "PostHog / Agent" chrome — e.g. the "joined" row. */
  author?: UserBasic | null;
}

export function channelFeedMessagesQueryKey(channelId: string | undefined) {
  return ["channel-feed-messages", channelId ?? "none"] as const;
}

// Announcements the card feed already represents, dropped to avoid saying the
// same thing twice: creation is the intro header's line (channel_created and
// its legacy client-posted context_created twin), and a CONTEXT.md build is
// its own plan-task card in the feed plus the intro card's "Creating…" state.
const REDUNDANT_EVENTS = new Set([
  "channel_created",
  "context_created",
  "context_md_building",
]);

// Render the announcement from its freeform content, with a generic fallback
// so an unknown future event still shows something.
function messageText(message: ChannelFeedMessage): string {
  const actor = userDisplayName(message.author ?? null);
  return message.content || `${actor} posted an update`;
}

/**
 * A channel's durable "PostHog agent" announcements (context created, CONTEXT.md
 * being built), oldest first, flattened to display text.
 */
export function useChannelFeedMessages(channelId: string | undefined): {
  messages: ChannelFeedSystemMessage[];
  isLoading: boolean;
} {
  const query = useAuthenticatedQuery<ChannelFeedMessage[]>(
    channelFeedMessagesQueryKey(channelId),
    (client) => client.getChannelFeed(channelId as string),
    {
      enabled: !!channelId,
      retry: false,
      refetchInterval: (query) =>
        shouldPollChannelFeed(query.state.error)
          ? CHANNEL_FEED_MESSAGES_POLL_INTERVAL_MS
          : false,
    },
  );
  const messages = useMemo(
    () =>
      (query.data ?? [])
        .filter((m) => !REDUNDANT_EVENTS.has(m.event))
        .map((m) => ({
          id: m.id,
          createdAt: m.created_at,
          text: messageText(m),
        })),
    [query.data],
  );
  return { messages, isLoading: query.isLoading };
}
