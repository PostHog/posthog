import {
  reviewerAvatarToneClass,
  reviewerInitials,
} from "@posthog/core/inbox/artefacts";

interface ReviewerAvatarProps {
  name?: string | null;
  email?: string | null;
  seed: string;
  size?: "sm" | "md";
  className?: string;
}

const SIZE_CLASS = {
  sm: "h-5 w-5 text-[9px]",
  md: "h-6 w-6 text-[10px]",
} as const;

export function ReviewerAvatar({
  name,
  email,
  seed,
  size = "md",
  className = "",
}: ReviewerAvatarProps) {
  const initials = reviewerInitials(name, email);
  const toneClass = reviewerAvatarToneClass(seed);

  return (
    <span
      className={[
        "inline-flex shrink-0 items-center justify-center rounded-full font-semibold leading-none",
        SIZE_CLASS[size],
        toneClass,
        className,
      ].join(" ")}
      aria-hidden
    >
      {initials}
    </span>
  );
}
