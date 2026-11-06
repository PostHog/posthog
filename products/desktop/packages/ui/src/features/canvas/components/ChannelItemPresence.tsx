import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import { presenceTier } from "@posthog/core/canvas/presence";
import {
  type AvatarPerson,
  UserAvatar,
} from "@posthog/ui/features/auth/UserAvatar";
import { PresenceAvatar } from "@posthog/ui/features/canvas/components/PresenceAvatars";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { useNow } from "@posthog/ui/hooks/useNow";

export function canvasAuthor(canvas: DashboardRecord): AvatarPerson | null {
  if (canvas.createdByUser) return canvas.createdByUser;
  if (!canvas.createdBy && !canvas.createdByUuid) return null;
  const [first, ...rest] = (canvas.createdBy ?? "")
    .split(/\s+/)
    .filter(Boolean);
  return {
    uuid: canvas.createdByUuid,
    first_name: first ?? null,
    last_name: rest.join(" ") || null,
  };
}

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

export function RowPresence({
  item,
  currentUserUuid,
}: {
  item: ChannelItemModel;
  currentUserUuid?: string;
}) {
  const author = rowAuthor(item);
  if (!author) return null;
  // Presence tells you who else is here, so your own face is noise.
  if (currentUserUuid && author.user.uuid === currentUserUuid) return null;
  if (presenceTier(item.ts, Date.now()) === "idle") return null;
  return <ActiveRowPresence item={item} author={author} />;
}

function ActiveRowPresence({
  item,
  author,
}: {
  item: ChannelItemModel;
  author: NonNullable<ReturnType<typeof rowAuthor>>;
}) {
  const tier = presenceTier(item.ts, useNow());
  if (tier === "idle") return null;
  return (
    <PresenceAvatar
      user={author.user}
      tier={tier}
      label={
        tier === "live"
          ? `${author.label} is working on this`
          : `${author.label} was here recently`
      }
    />
  );
}

export function ActivityPresenceAvatar({
  user,
  label,
  activityAt,
  size = "xs",
}: {
  user: AvatarPerson | null | undefined;
  label: string;
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
