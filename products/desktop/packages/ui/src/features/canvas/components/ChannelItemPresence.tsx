import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { presenceTier } from "@posthog/core/canvas/presence";
import {
  type AvatarPerson,
  UserAvatar,
} from "@posthog/ui/features/auth/UserAvatar";
import { PresenceAvatar } from "@posthog/ui/features/canvas/components/PresenceAvatars";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { useNow } from "@posthog/ui/hooks/useNow";

/**
 * Whose face a row wears. A session carries its author as a user record; a
 * canvas may only carry a name, which is still enough to draw initials.
 */
export function rowAuthor(
  item: ChannelItemModel,
): { user: AvatarPerson; label: string } | null {
  if (item.authorUser) {
    return { user: item.authorUser, label: userDisplayName(item.authorUser) };
  }
  if (item.kind === "task") return null;
  const name = item.authorName;
  if (!name && !item.authorUuid) return null;
  const [first, ...rest] = (name ?? "").split(/\s+/).filter(Boolean);
  return {
    user: {
      uuid: item.authorUuid,
      first_name: first ?? null,
      last_name: rest.join(" ") || null,
    },
    label: name ?? "Unknown",
  };
}

/**
 * The face of whoever is working on a row, shown only while the item is live or
 * recently active — a quiet row stays clean.
 *
 * Idle is decided here, once, off the clock: an item's activity time is fixed,
 * so a row that is idle now stays idle until its item changes, and re-rendering
 * it every minute would buy nothing. Only a row with a face to fade subscribes.
 */
export function RowPresence({
  item,
  currentUserUuid,
}: {
  item: ChannelItemModel;
  currentUserUuid?: string;
}) {
  const author = rowAuthor(item);
  if (!author) return null;
  if (presenceTier(item.ts, Date.now()) === "idle") return null;
  return (
    <ActiveRowPresence
      item={item}
      author={author}
      isCurrentUser={author.user.uuid === currentUserUuid}
    />
  );
}

/**
 * Subscribed to the clock rather than reading it once: the row is memoized on
 * its item, which a poll returning the same rows leaves untouched, so nothing
 * else would re-render it as the live window closes and the recent one ends.
 */
function ActiveRowPresence({
  item,
  author,
  isCurrentUser,
}: {
  item: ChannelItemModel;
  author: NonNullable<ReturnType<typeof rowAuthor>>;
  isCurrentUser: boolean;
}) {
  const tier = presenceTier(item.ts, useNow());
  if (tier === "idle") return null;
  return (
    <PresenceAvatar
      user={author.user}
      tier={tier}
      label={
        isCurrentUser && tier === "live"
          ? "You are working on this"
          : isCurrentUser
            ? "You were here recently"
            : tier === "live"
              ? `${author.label} is working on this`
              : `${author.label} was here recently`
      }
    />
  );
}

/**
 * One person's face with the presence mark their thing's last activity earns:
 * a pulsing dot while it is happening, a quiet one for a while after, nothing
 * once it is old. A row keeps the plain face either way, so the column does
 * not jump as things go quiet.
 *
 * Presence here is derived from activity, not from a viewer channel: the app
 * has nothing reporting who has a page open, so "right now" means "something
 * happened here in the last few minutes".
 */
export function ActivityPresenceAvatar({
  user,
  label,
  activityAt,
  size = "xs",
}: {
  user: AvatarPerson | null | undefined;
  /** What the person is doing, for the hover text: "on this session". */
  label: string;
  /** When the thing last moved, epoch ms or an ISO string. */
  activityAt: number | string | null | undefined;
  size?: "lg" | "default" | "sm" | "xs";
}) {
  const now = useNow();
  if (!user) return null;
  const ts =
    typeof activityAt === "string"
      ? Date.parse(activityAt)
      : (activityAt ?? Number.NaN);
  const tier = Number.isNaN(ts) ? "idle" : presenceTier(ts, now);
  const name = userDisplayName(user);
  if (tier === "idle") {
    return (
      <span className="shrink-0" title={name}>
        <UserAvatar user={user} size={size} />
      </span>
    );
  }
  return (
    <PresenceAvatar
      user={user}
      tier={tier}
      size={size}
      label={
        tier === "live"
          ? `${name} is working ${label}`
          : `${name} was here recently`
      }
    />
  );
}
