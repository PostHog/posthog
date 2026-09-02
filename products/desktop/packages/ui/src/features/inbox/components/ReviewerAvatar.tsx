import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";

interface ReviewerAvatarProps {
  name?: string | null;
  email?: string | null;
  seed: string;
  size?: "sm" | "md";
  className?: string;
}

const QUILL_SIZE = { sm: "xs", md: "sm" } as const;

// Adapts a teammate's flat display name onto the app-wide UserAvatar, which
// wants first/last for initials.
export function ReviewerAvatar({
  name,
  email,
  seed,
  size = "md",
  className,
}: ReviewerAvatarProps) {
  const parts = name?.trim().split(/\s+/).filter(Boolean) ?? [];
  return (
    <UserAvatar
      user={{
        uuid: seed,
        email,
        first_name: parts[0],
        last_name: parts.length > 1 ? parts[parts.length - 1] : undefined,
      }}
      size={QUILL_SIZE[size]}
      className={className}
    />
  );
}
