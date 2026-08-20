import { resolvePanelDrag } from "@posthog/ui/features/navigation/rightPanelStore";
import { ResizeHandle } from "@posthog/ui/primitives/ResizeHandle";
import React from "react";

/**
 * The panel's resize handle, on its inner edge. The panel is anchored to the
 * right of the row it sits in, so the width being asked for is the pointer's
 * distance from that edge - and the row, not the window, is also what the width
 * is held to, because the panel never reaches over the nav beside it.
 *
 * What each pointer position means is `resolvePanelDrag`; what lives here is
 * carrying it out and cleaning up after the drag.
 */
export function PanelResizeHandle({
  panelRef,
  open,
  expanded,
  width,
  isResizing,
  setIsResizing,
  setWidth,
  setOpen,
  setExpanded,
}: {
  /** The panel layer, whose parent is the row the panel is measured against. */
  panelRef: React.RefObject<HTMLDivElement | null>;
  open: boolean;
  expanded: boolean;
  /** The panel's own width, which an expanded panel is holding rather than using. */
  width: number;
  isResizing: boolean;
  setIsResizing: (isResizing: boolean) => void;
  setWidth: (width: number) => void;
  setOpen: (open: boolean) => void;
  setExpanded: (expanded: boolean) => void;
}) {
  const rowRef = React.useRef({ right: 0, width: 0 });
  // A drag that walks the panel down to its floor on the way to closing it
  // would leave that floor as the width to reopen at, so the width the drag
  // started from is what a close puts back.
  const startWidthRef = React.useRef(0);
  // Read by the mouseup, which can fire before React has re-registered these
  // listeners with the post-close `open`, so the closure can't be trusted.
  const closedRef = React.useRef(false);

  const state = React.useRef({
    open,
    expanded,
    setWidth,
    setOpen,
    setExpanded,
    setIsResizing,
  });
  state.current = {
    open,
    expanded,
    setWidth,
    setOpen,
    setExpanded,
    setIsResizing,
  };

  React.useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      const { right, width: rowWidth } = rowRef.current;
      const {
        open,
        expanded,
        setWidth: apply,
        setOpen: toggle,
        setExpanded: expand,
      } = state.current;

      const drag = resolvePanelDrag({
        pointer: right - e.clientX,
        rowWidth,
        open,
        expanded,
      });

      switch (drag.action) {
        case "hold":
          return;
        case "resize":
          apply(drag.width);
          return;
        case "collapse":
          expand(false);
          apply(drag.width);
          return;
        case "close":
          toggle(false);
          closedRef.current = true;
          return;
        case "reopen":
          toggle(true);
          closedRef.current = false;
          apply(drag.width);
          return;
      }
    };

    const handleMouseUp = () => {
      state.current.setIsResizing(false);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      if (closedRef.current) state.current.setWidth(startWidthRef.current);
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isResizing]);

  // Closing the panel mid-drag unmounts the handle before any mouseup arrives,
  // which would leave the app with a col-resize cursor, text selection
  // disabled, and a stuck isResizing.
  const unmountResetRef = React.useRef({ isResizing, setIsResizing });
  unmountResetRef.current = { isResizing, setIsResizing };
  React.useEffect(
    () => () => {
      const { isResizing: active, setIsResizing: reset } =
        unmountResetRef.current;
      if (active) {
        reset(false);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }
    },
    [],
  );

  return (
    <ResizeHandle
      edge="left"
      tooltip="Resize"
      isResizing={isResizing}
      onMouseDown={(e) => {
        e.preventDefault();
        const row = panelRef.current?.parentElement?.getBoundingClientRect();
        rowRef.current = {
          right: row?.right ?? window.innerWidth,
          width: row?.width ?? window.innerWidth,
        };
        // The panel's own width rather than the one on screen: a drag that
        // starts expanded and ends closed should reopen at the width expanding
        // was covering, not at the whole row.
        startWidthRef.current = width;
        closedRef.current = false;
        setIsResizing(true);
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
      }}
    />
  );
}
