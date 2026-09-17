import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { cn } from "@posthog/quill";
import { ChannelItemRowView } from "@posthog/ui/features/canvas/components/ChannelItemRow";
import { useChannelTaskStatus } from "@posthog/ui/features/canvas/hooks/useChannelTaskStatus";
import { DragBatchLabel } from "@posthog/ui/features/sidebar/components/DragBatchLabel";
import { getPinDropAction } from "@posthog/ui/features/sidebar/taskListDragAndDrop";
import type { PinDrag } from "@posthog/ui/features/sidebar/usePinDrag";
import {
  AnimatePresence,
  type MotionValue,
  motion,
  useReducedMotion,
} from "framer-motion";
import { createPortal } from "react-dom";

/**
 * The card that follows the pointer during a pin drag, badged with what
 * releasing here would do, unbadged where it would do nothing.
 *
 * Portalled to the theme root for two reasons. The sidebar's panes slide on a
 * transform, which `position: fixed` would resolve against; and Radix scopes
 * the palette to that element, so a card on the body draws colours as
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
  const host =
    document.querySelector<HTMLElement>(".radix-themes") ?? document.body;
  // Skips the PR lookup: that is a query into git per row, and the row under
  // the pointer is already paying for it.
  const status = useChannelTaskStatus(drag.items[0], { withPrStatus: false });
  const action = getPinDropAction(drag.sourcePinned, drag.overPinned);
  const draggedCount = drag.items.length;
  const spring = prefersReducedMotion
    ? { duration: 0 }
    : ({ type: "spring", stiffness: 500, damping: 34 } as const);

  return createPortal(
    <motion.div
      style={{ x, y, width: drag.previewWidth }}
      className="pointer-events-none fixed top-0 left-0 z-50"
    >
      {/* Two offset layers behind the card, so a batch looks like a stack
          before its label is read. */}
      {draggedCount > 1 ? (
        <>
          <div className="absolute inset-x-2 top-2 h-full rounded-md border border-border bg-background shadow-sm" />
          <div className="absolute inset-x-1 top-1 h-full rounded-md border border-border bg-background shadow-sm" />
        </>
      ) : null}
      <div className="relative overflow-hidden rounded-md border border-border bg-background shadow-lg">
        {draggedCount > 1 ? (
          <DragBatchLabel count={draggedCount} />
        ) : (
          <ChannelItemRowView
            item={drag.items[0]}
            status={status}
            isActive={false}
            showPinBadge={false}
          />
        )}
      </div>
      <AnimatePresence>
        {action !== null ? (
          <motion.span
            // Keyed on the action, so crossing into the run swaps the badge
            // rather than retitling the one already there.
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
