import { avatarColor } from "@posthog/core/auth/avatarColor";
import type { UserLike } from "@posthog/core/auth/userInitials";
import { Avatar, AvatarFallback, AvatarImage } from "@posthog/quill";
import {
  rememberAvatarImageStatus,
  rememberedAvatarImageStatus,
} from "@posthog/ui/features/auth/avatarImageStatus";
import { useGravatarUrl } from "@posthog/ui/features/auth/useGravatarUrl";
import { getUserInitials } from "@posthog/ui/features/auth/userInitials";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { cachedImageUrl } from "@posthog/ui/shell/cachedImageUrl";

type AvatarSize = "lg" | "default" | "sm" | "xs";

// The minimum a surface needs to know about a person to draw them. `UserBasic`
// satisfies it, and so do leaner shapes like inbox teammates.
export interface AvatarPerson extends UserLike {
  uuid?: string | null;
}

interface UserAvatarProps {
  user?: AvatarPerson | null;
  size?: AvatarSize;
  className?: string;
  title?: string;
}

const KNOWN_IMAGE_FALLBACK_DELAY_MS = 300;

// A person's avatar: Gravatar (by email) when one exists, otherwise a colored
// initials bubble. The color is seeded off a stable identifier so each person keeps
// one hue everywhere. When the Gravatar image loads it covers the colored fallback.
export function UserAvatar({
  user,
  size = "default",
  className,
  title,
}: UserAvatarProps) {
  const gravatarUrl = useGravatarUrl(user?.email);
  const src = gravatarUrl ? cachedImageUrl(gravatarUrl) : undefined;
  const knownStatus = rememberedAvatarImageStatus(src);
  const seed = user?.uuid ?? user?.email ?? userDisplayName(user);
  const color = avatarColor(seed);

  return (
    <Avatar size={size} className={className} title={title}>
      {src && knownStatus !== "error" ? (
        <AvatarImage
          src={src}
          alt={userDisplayName(user)}
          onLoadingStatusChange={(status) => {
            if (status === "loaded" || status === "error") {
              rememberAvatarImageStatus(src, status);
            }
          }}
        />
      ) : null}
      {/* Base UI reads `delay` once, when the fallback mounts, and never arms the
          hold again. A surface that keeps one avatar and swaps the person, such as
          the handoff dialog, must remount the fallback to get the hold for the new
          image. */}
      <AvatarFallback
        key={src}
        delay={
          knownStatus === "loaded" ? KNOWN_IMAGE_FALLBACK_DELAY_MS : undefined
        }
        style={{ backgroundColor: color.bg, color: color.text }}
      >
        {getUserInitials(user)}
      </AvatarFallback>
    </Avatar>
  );
}
