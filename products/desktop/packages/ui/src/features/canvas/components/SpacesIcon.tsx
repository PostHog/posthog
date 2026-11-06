import type { IconProps } from "@phosphor-icons/react";
import { useChannelPaneStore } from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";

const SQUARES = [
  { x: 40, y: 40 },
  { x: 136, y: 40 },
  { x: 40, y: 136 },
  { x: 136, y: 136 },
] as const;

/**
 * The rail's Spaces mark: four squares, with the last one lit while you are
 * inside a space rather than browsing the tree.
 */
export function SpacesIcon({ size = 16, weight, ...props }: IconProps) {
  const pane = useChannelPaneStore((s) => s.pane);
  const currentChannelId = useCurrentChannelStore((s) => s.currentChannelId);
  const inSpace = pane === "channel" && currentChannelId != null;
  const filled = weight === "fill";

  return (
    <svg
      viewBox="0 0 256 256"
      width={size}
      height={size}
      fill="none"
      role="presentation"
      {...props}
    >
      {SQUARES.map(({ x, y }, index) => {
        const lit = inSpace && index === SQUARES.length - 1;
        const color = lit ? "var(--primary)" : "currentColor";
        return filled || lit ? (
          <rect
            key={`${x}-${y}`}
            x={x}
            y={y}
            width={80}
            height={80}
            rx={20}
            fill={color}
          />
        ) : (
          <rect
            key={`${x}-${y}`}
            x={x + 8}
            y={y + 8}
            width={64}
            height={64}
            rx={12}
            stroke={color}
            strokeWidth={16}
          />
        );
      })}
    </svg>
  );
}
