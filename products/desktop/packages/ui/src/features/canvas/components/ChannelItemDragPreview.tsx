import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { cn } from "@posthog/quill";
import { ChannelItemRowView } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import { useChannelTaskStatus } from "@posthog/ui/features/canvas/hooks/useChannelTaskStatus";
import { getPinDropAction } from "@posthog/ui/features/sidebar/taskListDragAndDrop";
import type { PinDrag } from "@posthog/ui/features/sidebar/usePinDrag";
import {
  AnimatePresence,
  type MotionValue,
  motion,
  useReducedMotion,
} from "framer-motion";
import { useMemo } from "react";
import { createPortal } from "react-dom";

/**
 * The session card that follows the pointer during a pin drag, badged with what
 * releasing here would do — and unbadged where releasing would do nothing.
 *
 * Portalled out of the sidebar because its two panes slide on a transform, and
 * a transformed ancestor is what `position: fixed` resolves against — the card
 * would be positioned inside the pane, and clipped by it. It lands on the theme
 * root rather than the body: Radix scopes `--accent-*` and the rest of the
 * palette to that element, so a card on the body draws its colours as
 * transparent.
 */
export function ChannelItemDragPreview({
  drag,
  x,
  y,
}: {
  drag: PinDrag<ChannelItemModel>;
  x: MotionValue<number>;
  y: MotionValue<number>;
}) {
  const prefersReducedMotion = useReducedMotion();
  const host = useMemo(
    () => document.querySelector<HTMLElement>(".radix-themes") ?? document.body,
    [],
  );
  // The card is a picture of the row, so it takes the marks the row already
  // shows and skips the PR lookup behind them — that one is a query into git
  // per row, and the row under the pointer is already paying for it.
  const status = useChannelTaskStatus(drag.item, { withPrStatus: false });
  const action = getPinDropAction(drag.sourcePinned, drag.overPinned);
  const spring = prefersReducedMotion
    ? { duration: 0 }
    : ({ type: "spring", stiffness: 500, damping: 34 } as const);

  return createPortal(
    <motion.div
      style={{ x, y, width: drag.previewWidth }}
      className="pointer-events-none fixed top-0 left-0 z-50"
    >
      <div className="overflow-hidden rounded-md border border-border bg-background shadow-lg">
        <ChannelItemRowView
          item={drag.item}
          status={status}
          isActive={false}
          showPinBadge={false}
        />
      </div>
      <AnimatePresence>
        {action !== null ? (
          <motion.span
            // Keyed on the action, so crossing into the pinned run swaps the
            // badge rather than retitling the one already there.
            key={String(action)}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={spring}
            className={cn(
              "absolute top-full left-2 mt-1 rounded-full px-2 py-0.5 font-medium text-[11px] shadow-sm",
              action
                ? "bg-primary text-primary-foreground"
                : "bg-destructive text-destructive-foreground",
            )}
          >
            {action ? "Add to pinned" : "Remove from pinned"}
          </motion.span>
        ) : null}
      </AnimatePresence>
    </motion.div>,
    host,
  );
}
