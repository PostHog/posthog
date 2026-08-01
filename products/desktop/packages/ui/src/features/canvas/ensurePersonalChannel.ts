import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { PERSONAL_CHANNEL_NAME } from "@posthog/ui/features/canvas/hooks/useTaskChannels";

// The "me" folder is provisioned on first use, and folder creation is not
// server-side idempotent by path — so two callers racing before the first
// create lands in the channels cache would each make their own "me". The entry
// points are trivially concurrent (Cmd+T's new tab, the sidebar row, its "+"
// menu), so they share one in-flight create rather than guarding separately:
// per-caller guards would still race each other.
let inFlight: Promise<Channel> | null = null;
// The in-flight promise alone isn't enough: it settles the moment the POST
// returns, but callers pass the `channels` from their last render, which hasn't
// re-rendered with the seeded cache yet. A click landing in that gap sees
// neither an existing "me" nor an in-flight create, and makes a second one.
// Remember what was created until the list catches up.
let created: Channel | null = null;

/**
 * The user's "me" folder, creating it once if it doesn't exist yet. Concurrent
 * callers await the same create. Rejects if the create fails; callers own the
 * messaging.
 */
export async function ensurePersonalChannel(
  channels: readonly Channel[],
  createChannel: (name: string) => Promise<Channel>,
): Promise<Channel> {
  const existing = channels.find((c) => c.name === PERSONAL_CHANNEL_NAME);
  if (existing) {
    // The list is authoritative once it carries the folder: drop the memo, so a
    // deleted-then-recreated "me" resolves fresh rather than to a dead id.
    created = null;
    return existing;
  }
  if (created) return created;
  if (!inFlight) {
    inFlight = createChannel(PERSONAL_CHANNEL_NAME)
      .then((channel) => {
        created = channel;
        return channel;
      })
      .finally(() => {
        inFlight = null;
      });
  }
  return inFlight;
}
