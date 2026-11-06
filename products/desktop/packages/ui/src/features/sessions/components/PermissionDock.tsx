import { CaretDown, CaretUp } from "@phosphor-icons/react";
import {
  Button,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { ComposerWidth } from "@posthog/ui/features/sessions/components/ComposerWidth";
import {
  usePermissionDockHeight,
  useSessionViewActions,
} from "@posthog/ui/features/sessions/sessionViewStore";
import { useCallback, useEffect, useRef, useState } from "react";

/** Shortest the dock goes, and the room the thread above always keeps. */
const MIN_DOCK_HEIGHT = 96;
const MIN_THREAD_HEIGHT = 120;
/** How far one arrow-key press on the handle moves the dock's ceiling. */
const RESIZE_STEP = 40;

/**
 * Holds a permission or question card below the thread, capped so the card
 * never swallows the conversation that led to it: a long option list scrolls
 * inside the dock, the handle re-sizes it, and hiding it drops it to a single
 * bar so the thread can be read in full before answering.
 *
 * Hidden content stays mounted — a half-filled multi-question answer survives
 * the round trip, and a `display: none` card cannot hold focus, so the card's
 * digit and arrow shortcuts stand down while it is out of sight.
 */
export function PermissionDock({
  compact,
  children,
}: {
  compact: boolean;
  children: React.ReactNode;
}) {
  const height = usePermissionDockHeight();
  const { setPermissionDockHeight } = useSessionViewActions();
  const [isHidden, setIsHidden] = useState(false);
  const dockRef = useRef<HTMLDivElement>(null);
  /** Set while a drag is in flight, so an unmount can end it. */
  const endDragRef = useRef<(() => void) | null>(null);
  // What the handle reports to assistive tech. Measured rather than read off
  // the store, because until the first drag the dock sits at its default share
  // of the column and has no stored height to report.
  const [reportedHeight, setReportedHeight] = useState(MIN_DOCK_HEIGHT);
  const [maxHeightAllowed, setMaxHeightAllowed] = useState(MIN_DOCK_HEIGHT);

  const measureMax = useCallback(() => {
    const available =
      dockRef.current?.parentElement?.getBoundingClientRect().height ?? 0;
    const max = Math.max(MIN_DOCK_HEIGHT, available - MIN_THREAD_HEIGHT);
    setMaxHeightAllowed(max);
    return max;
  }, []);

  const measureDock = useCallback(
    () => Math.round(dockRef.current?.getBoundingClientRect().height ?? 0),
    [],
  );

  // Both caps are CSS, so the dock re-sizes with the window without React
  // hearing about it. Re-measuring whenever the handle is reached keeps what a
  // screen reader announces true at the moment it is read.
  const refreshReportedRange = useCallback(() => {
    measureMax();
    setReportedHeight(measureDock());
  }, [measureMax, measureDock]);

  const attachDock = useCallback(
    (node: HTMLDivElement | null) => {
      dockRef.current = node;
      if (!node) return;
      refreshReportedRange();
    },
    [refreshReportedRange],
  );

  const resizeTo = useCallback(
    (next: number) => {
      const clamped = Math.round(
        Math.min(measureMax(), Math.max(MIN_DOCK_HEIGHT, next)),
      );
      setPermissionDockHeight(clamped);
      setReportedHeight(clamped);
    },
    [measureMax, setPermissionDockHeight],
  );

  const handleResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      const startY = e.clientY;
      const startHeight = dockRef.current?.getBoundingClientRect().height ?? 0;

      const onMouseMove = (moveEvent: MouseEvent) => {
        // A button released outside the window delivers no mouseup, so the
        // first move back inside — the one reporting no button held — is what
        // ends that drag.
        if (moveEvent.buttons === 0) {
          endDrag();
          return;
        }
        resizeTo(startHeight + (startY - moveEvent.clientY));
      };
      const endDrag = () => {
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", endDrag);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        endDragRef.current = null;
      };

      document.body.style.cursor = "row-resize";
      document.body.style.userSelect = "none";
      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", endDrag);
      endDragRef.current = endDrag;
    },
    [resizeTo],
  );

  // Answering the prompt unmounts the dock, and that can land mid-drag: without
  // this the listeners outlive it, and the whole app keeps the resize cursor
  // with text selection off.
  useEffect(() => () => endDragRef.current?.(), []);

  const handleResizeKey = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
      e.preventDefault();
      resizeTo(
        measureDock() + (e.key === "ArrowUp" ? RESIZE_STEP : -RESIZE_STEP),
      );
    },
    [measureDock, resizeTo],
  );

  // A height dragged in a tall window outlives that window: the store keeps it
  // app-wide, so the reserve is re-applied in CSS rather than trusted from the
  // drag that set it.
  const maxHeight =
    height !== null
      ? `min(${height}px, calc(100% - ${MIN_THREAD_HEIGHT}px))`
      : undefined;

  return (
    <div
      ref={attachDock}
      className={`flex min-h-0 shrink-0 flex-col ${
        isHidden ? "" : compact ? "max-h-[50%]" : "max-h-[60%]"
      }`}
      style={{ maxHeight: isHidden ? undefined : maxHeight }}
    >
      <div
        className={`flex shrink-0 items-center gap-2 px-2 ${
          // Hidden, the bar is the only thing between the thread and the window
          // edge, so it needs an edge of its own to not read as another message.
          isHidden ? "border-(--gray-4) border-t py-1" : ""
        }`}
      >
        {isHidden ? (
          <Text className="flex-1 truncate text-(--gray-11) text-[13px]">
            Waiting for your response
          </Text>
        ) : (
          // biome-ignore lint/a11y/useSemanticElements: <hr> is void, so it cannot hold the grip it would have to draw
          <div
            role="separator"
            aria-orientation="horizontal"
            aria-label="Resize"
            aria-valuenow={reportedHeight}
            aria-valuemin={MIN_DOCK_HEIGHT}
            aria-valuemax={maxHeightAllowed}
            tabIndex={0}
            onFocus={refreshReportedRange}
            onMouseDown={handleResizeStart}
            onKeyDown={handleResizeKey}
            className="group flex flex-1 cursor-row-resize justify-center py-1 outline-none"
          >
            <div className="h-1 w-8 rounded-full bg-(--gray-6) group-hover:bg-(--gray-8) group-focus-visible:bg-(--gray-8)" />
          </div>
        )}
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                variant="default"
                size="icon-sm"
                aria-label={isHidden ? "Show" : "Hide"}
                onClick={() => setIsHidden(!isHidden)}
              >
                {isHidden ? <CaretUp size={12} /> : <CaretDown size={12} />}
              </Button>
            }
          />
          <TooltipContent>
            {isHidden ? "Show the options again" : "Hide to read the thread"}
          </TooltipContent>
        </Tooltip>
      </div>
      <div className={isHidden ? "hidden" : "min-h-0 flex-1 overflow-y-auto"}>
        <ComposerWidth compact={compact}>{children}</ComposerWidth>
      </div>
    </div>
  );
}
