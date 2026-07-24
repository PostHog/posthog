import { cn } from "@posthog/quill";
import posthogIcon from "../../assets/posthog-icon.svg";

const SIZE = {
  sm: { className: "h-[18px] w-[18px]", pixels: 28 },
  md: { className: "h-[20px] w-[20px]", pixels: 32 },
} as const;

interface SuggestedReviewerAvatarProps {
  githubLogin: string;
  size?: keyof typeof SIZE;
  className?: string;
}

/** GitHub bots are suffixed with `[bot]`, e.g. `dependabot[bot]`. */
function isBotLogin(githubLogin: string): boolean {
  return githubLogin.endsWith("[bot]");
}

const POSTHOG_BOT_LOGIN = "posthog[bot]";

/** GitHub profile avatar for suggested reviewers – matches SuggestedReviewersEditor. */
export function SuggestedReviewerAvatar({
  githubLogin,
  size = "md",
  className,
}: SuggestedReviewerAvatarProps) {
  const config = SIZE[size];

  if (isBotLogin(githubLogin)) {
    // GitHub bot avatars are noisy generic icons; render the PostHog logo for our
    // own bot and an empty space sized like the avatar for every other bot.
    if (githubLogin === POSTHOG_BOT_LOGIN) {
      return (
        <img
          src={posthogIcon}
          alt=""
          className={cn("shrink-0 object-contain", config.className, className)}
        />
      );
    }

    return (
      <span
        aria-hidden
        className={cn("shrink-0", config.className, className)}
      />
    );
  }

  return (
    <img
      src={`https://github.com/${githubLogin}.png?size=${config.pixels}`}
      alt=""
      className={cn(
        "github-avatar shrink-0 rounded-full",
        config.className,
        className,
      )}
      onLoad={(event) => event.currentTarget.classList.add("loaded")}
    />
  );
}
