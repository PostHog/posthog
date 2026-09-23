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
