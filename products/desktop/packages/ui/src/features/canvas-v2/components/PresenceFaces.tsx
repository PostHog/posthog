import type { PresencePeer } from "@posthog/core/canvas-v2/boardPresence";
import { Text, Tooltip, TooltipContent, TooltipTrigger } from "@posthog/quill";
import {
  PRESENCE_FACES_LABEL,
  presenceOverflowLabel,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import type { ReactElement } from "react";

/** Faces beyond this many collapse into one count badge. */
const MAX_FACES = 5;

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
    <ul aria-label={PRESENCE_FACES_LABEL} className="flex items-center gap-0.5">
      {shown.map((peer) => (
        <li key={peer.clientId}>
          <Tooltip>
            <TooltipTrigger
              render={
                <div
                  className="flex size-5 items-center justify-center rounded-full font-medium text-[9px] text-white"
                  style={{ backgroundColor: peer.color }}
                >
                  {peer.initials}
                </div>
              }
            />
            <TooltipContent side="bottom">{peer.name}</TooltipContent>
          </Tooltip>
        </li>
      ))}
      {hidden.length > 0 ? (
        <li>
          <Tooltip>
            <TooltipTrigger
              render={
                <div className="flex size-5 items-center justify-center rounded-full bg-(--gray-5)">
                  <Text size="xs" variant="muted">
                    {presenceOverflowLabel(hidden.length)}
                  </Text>
                </div>
              }
            />
            <TooltipContent side="bottom">
              {hidden.map((peer) => peer.name).join(", ")}
            </TooltipContent>
          </Tooltip>
        </li>
      ) : null}
    </ul>
  );
}
