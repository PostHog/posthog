import {
  type BoardPaneRect,
  fragmentScreenRect,
  worldToScreen,
} from "@posthog/core/canvas-v2/boardGeometry";
import type { PresencePeer } from "@posthog/core/canvas-v2/boardPresence";
import type { CanvasV2Fragment, CanvasV2Viewport } from "@posthog/shared";
import type { ReactElement } from "react";

/** How long a cursor takes to slide from one ping to the next. */
const CURSOR_GLIDE_MS = 100;
/** Each further person's ring sits this far inside the one before it. */
const RING_INSET_PX = 3;

interface PresenceLayerProps {
  peers: readonly PresencePeer[];
  fragments: readonly CanvasV2Fragment[];
  viewport: CanvasV2Viewport;
  paneRect: BoardPaneRect;
}

interface PeerCursor {
  peer: PresencePeer;
  left: number;
  top: number;
}

interface PeerRing {
  key: string;
  color: string;
  textColor: string;
  name: string;
  inset: number;
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * Everybody else's cursors and held fragments, above the frame. The layer
 * never takes a pointer event, so it cannot get in the way of the board.
 */
export function PresenceLayer({
  peers,
  fragments,
  viewport,
  paneRect,
}: PresenceLayerProps): ReactElement | null {
  if (peers.length === 0) return null;

  const cursors: PeerCursor[] = [];
  for (const peer of peers) {
    if (!peer.cursor) continue;
    const point = worldToScreen(peer.cursor, viewport, paneRect);
    const left = point.x - paneRect.left;
    const top = point.y - paneRect.top;
    // A cursor off the visible board is hidden, not pinned to the edge.
    const inside =
      left >= 0 && top >= 0 && left <= paneRect.width && top <= paneRect.height;
    if (!inside) continue;
    cursors.push({ peer, left, top });
  }

  const rings: PeerRing[] = [];
  for (const [index, peer] of peers.entries()) {
    for (const id of peer.selectedIds) {
      const fragment = fragments.find((candidate) => candidate.id === id);
      if (!fragment) continue;
      const screen = fragmentScreenRect(fragment, viewport, paneRect);
      rings.push({
        key: `${peer.clientId}:${id}`,
        color: peer.color.bg,
        textColor: peer.color.text,
        name: peer.name,
        inset: index * RING_INSET_PX,
        left: screen.left - paneRect.left,
        top: screen.top - paneRect.top,
        width: screen.width,
        height: screen.height,
      });
    }
  }

  return (
    <div className="pointer-events-none absolute inset-0 z-30 overflow-hidden">
      {rings.map((ring) => (
        <div
          key={ring.key}
          className="absolute"
          style={{
            left: ring.left - ring.inset,
            top: ring.top - ring.inset,
            width: ring.width + ring.inset * 2,
            height: ring.height + ring.inset * 2,
            border: `1.5px solid ${ring.color}`,
            borderRadius: 4,
          }}
        >
          <span
            className="-top-[18px] absolute left-0 rounded-(--radius-1) px-1.5 font-medium text-[10px] leading-4 shadow-xs"
            style={{ backgroundColor: ring.color, color: ring.textColor }}
          >
            {ring.name}
          </span>
        </div>
      ))}
      {cursors.map(({ peer, left, top }) => (
        <div
          key={peer.clientId}
          className="absolute top-0 left-0 flex items-start"
          style={{
            transform: `translate3d(${left}px, ${top}px, 0)`,
            transition: `transform ${CURSOR_GLIDE_MS}ms linear`,
          }}
        >
          <svg
            aria-hidden="true"
            width="14"
            height="20"
            viewBox="0 0 14 20"
            fill="none"
          >
            <path
              d="M1 1L1 16.5L5.1 12.6L7.9 18.6L10.4 17.4L7.6 11.5L12.5 11.5Z"
              fill={peer.color.bg}
              stroke="white"
              strokeWidth="1.2"
            />
          </svg>
          <span
            className="-ml-1 mt-3.5 whitespace-nowrap rounded-full px-1.5 py-px font-medium text-[10px] leading-4 shadow-sm"
            style={{ backgroundColor: peer.color.bg, color: peer.color.text }}
          >
            {peer.name}
          </span>
        </div>
      ))}
    </div>
  );
}
