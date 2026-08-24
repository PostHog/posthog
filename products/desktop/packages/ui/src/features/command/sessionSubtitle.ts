import { channelDisplayName } from "@posthog/core/canvas/channelName";
import { formatRelativeTimeShort } from "@posthog/shared";

/**
 * The muted second line under a session's title in the command palette: where
 * it lives and how long ago it started.
 *
 * The space carries no `#`. The spaces layout dropped that mark everywhere else
 * it names a space, and a lone hash in this one list reads as a different kind
 * of thing.
 */
export function sessionSubtitle(input: {
  space?: string | null;
  repository?: string | null;
  createdAt?: string | null;
}): string | undefined {
  const parts = [
    input.repository ?? undefined,
    input.space ? channelDisplayName(input.space) : undefined,
    input.createdAt ? formatRelativeTimeShort(input.createdAt) : undefined,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : undefined;
}
