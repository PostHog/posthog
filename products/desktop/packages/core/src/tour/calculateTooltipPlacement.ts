import type { TooltipPlacement } from "@posthog/core/tour/types";

const TOOLTIP_MARGIN = 12;
const VIEWPORT_PADDING = 8;

const DEFAULT_ORDER: TooltipPlacement[] = ["right", "left", "top", "bottom"];

export interface Rect {
  top: number;
  left: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

export interface PlacedTooltip {
  placement: TooltipPlacement;
  x: number;
  y: number;
  arrowOffset: number;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export function calculateTooltipPlacement(
  targetRect: Rect,
  tooltipWidth: number,
  tooltipHeight: number,
  vw: number,
  vh: number,
  preferred?: TooltipPlacement,
): PlacedTooltip {
  const spaceRight = vw - targetRect.right;
  const spaceLeft = targetRect.left;
  const spaceAbove = targetRect.top;

  const targetCenterX = targetRect.left + targetRect.width / 2;
  const targetCenterY = targetRect.top + targetRect.height / 2;

  const order = preferred
    ? [preferred, ...DEFAULT_ORDER.filter((p) => p !== preferred)]
    : DEFAULT_ORDER;

  for (const placement of order) {
    switch (placement) {
      case "right": {
        if (spaceRight < tooltipWidth + TOOLTIP_MARGIN) break;
        const idealY = targetCenterY - tooltipHeight / 2;
        const y = clamp(
          idealY,
          VIEWPORT_PADDING,
          vh - VIEWPORT_PADDING - tooltipHeight,
        );
        return {
          placement,
          x: targetRect.right + TOOLTIP_MARGIN,
          y,
          arrowOffset: idealY - y,
        };
      }
      case "left": {
        if (spaceLeft < tooltipWidth + TOOLTIP_MARGIN) break;
        const idealY = targetCenterY - tooltipHeight / 2;
        const y = clamp(
          idealY,
          VIEWPORT_PADDING,
          vh - VIEWPORT_PADDING - tooltipHeight,
        );
        return {
          placement,
          x: targetRect.left - TOOLTIP_MARGIN - tooltipWidth,
          y,
          arrowOffset: idealY - y,
        };
      }
      case "top": {
        if (spaceAbove < tooltipHeight + TOOLTIP_MARGIN) break;
        const idealX = targetCenterX - tooltipWidth / 2;
        const x = clamp(
          idealX,
          VIEWPORT_PADDING,
          vw - VIEWPORT_PADDING - tooltipWidth,
        );
        return {
          placement,
          x,
          y: targetRect.top - TOOLTIP_MARGIN - tooltipHeight,
          arrowOffset: idealX - x,
        };
      }
      case "bottom": {
        const idealX = targetCenterX - tooltipWidth / 2;
        const x = clamp(
          idealX,
          VIEWPORT_PADDING,
          vw - VIEWPORT_PADDING - tooltipWidth,
        );
        return {
          placement,
          x,
          y: targetRect.bottom + TOOLTIP_MARGIN,
          arrowOffset: idealX - x,
        };
      }
    }
  }

  const idealX = targetCenterX - tooltipWidth / 2;
  const x = clamp(
    idealX,
    VIEWPORT_PADDING,
    vw - VIEWPORT_PADDING - tooltipWidth,
  );
  return {
    placement: "bottom",
    x,
    y: targetRect.bottom + TOOLTIP_MARGIN,
    arrowOffset: idealX - x,
  };
}
