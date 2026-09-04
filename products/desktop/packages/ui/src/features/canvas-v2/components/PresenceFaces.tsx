import type { PresencePeer } from "@posthog/core/canvas-v2/boardPresence";
import {
  AvatarGroup,
  Text,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { presenceOverflowLabel } from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import type { ReactElement } from "react";

const MAX_FACES = 5;
const TOOLTIP_DELAY_MS = 200;

/** Who else is on the board now, beside the sync chip. */
export function PresenceFaces({
  peers,
}: {
  peers: readonly PresencePeer[];
}): ReactElement | null {
  if (peers.length === 0) return null;
  const shown = peers.slice(0, MAX_FACES);
  const hidden = peers.slice(MAX_FACES);

  return (
    <TooltipProvider delay={TOOLTIP_DELAY_MS}>
      <AvatarGroup stacked reverse size="xs" aria-label="People on this board">
        {shown.map((peer) => (
          <Tooltip key={peer.clientId} disableHoverablePopup>
            <TooltipTrigger
              render={
                <span
                  aria-label={peer.name}
                  role="img"
                  className="relative flex shrink-0"
                >
                  <UserAvatar size="xs" user={peer.user} />
                </span>
              }
            />
            <TooltipContent
              side="bottom"
              className="pointer-events-none select-none"
            >
              {peer.name}
            </TooltipContent>
          </Tooltip>
        ))}
        {hidden.length > 0 ? (
          <Tooltip disableHoverablePopup>
            <TooltipTrigger
              render={
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-(--gray-5) ring-2 ring-background">
                  <Text size="xxs" variant="muted">
                    {presenceOverflowLabel(hidden.length)}
                  </Text>
                </span>
              }
            />
            <TooltipContent
              side="bottom"
              className="pointer-events-none select-none"
            >
              {hidden.map((peer) => peer.name).join(", ")}
            </TooltipContent>
          </Tooltip>
        ) : null}
      </AvatarGroup>
    </TooltipProvider>
  );
}
