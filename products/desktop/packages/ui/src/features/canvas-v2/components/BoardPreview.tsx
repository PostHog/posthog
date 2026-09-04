import type { CanvasV2BoardSummary } from "@posthog/shared";
import type { ReactElement } from "react";

/** Free space around the boxes, as a share of the board, so none touch an edge. */
const PADDING_SHARE = 0.06;

type PreviewBox = CanvasV2BoardSummary["preview"][number];

/** The shape of a board, drawn from the boxes the list carries. */
export function BoardPreview({
  boxes,
}: {
  boxes: readonly PreviewBox[];
}): ReactElement | null {
  if (boxes.length === 0) return null;

  const left = Math.min(...boxes.map((box) => box.x));
  const top = Math.min(...boxes.map((box) => box.y));
  const right = Math.max(...boxes.map((box) => box.x + box.w));
  const bottom = Math.max(...boxes.map((box) => box.y + box.h));
  const width = Math.max(1, right - left);
  const height = Math.max(1, bottom - top);
  const padding = Math.max(width, height) * PADDING_SHARE;

  return (
    <svg
      aria-hidden="true"
      className="h-full w-full"
      viewBox={`${left - padding} ${top - padding} ${width + padding * 2} ${height + padding * 2}`}
      preserveAspectRatio="xMidYMid meet"
    >
      <title>Board layout</title>
      {boxes.map((box) => (
        <rect
          key={`${box.x}:${box.y}:${box.w}:${box.h}`}
          x={box.x}
          y={box.y}
          width={box.w}
          height={box.h}
          rx={10}
          vectorEffect="non-scaling-stroke"
          className="fill-(--gray-a4) stroke-(--gray-a7)"
        />
      ))}
    </svg>
  );
}
