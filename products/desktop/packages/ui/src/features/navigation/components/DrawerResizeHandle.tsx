import { resolveExpandedWidth } from "@posthog/ui/features/navigation/rightPanelStore";
import React from "react";

/**
 * The expanded panel's resize handle, on the inner edge of its drawer. The
 * drawer is anchored to the window's right edge, so the width it is being asked
 * for is the pointer's distance from that edge.
 *
 * It sits inside the drawer's popup rather than beside it, so the shield a drag
 * puts over the window still counts as part of the drawer - a mouseup landing
 * outside it would otherwise read as an outside press and collapse the panel
 * mid-drag.
 */
export function DrawerResizeHandle({
  isResizing,
  setIsResizing,
  setWidth,
}: {
  isResizing: boolean;
  setIsResizing: (isResizing: boolean) => void;
  setWidth: (width: number) => void;
}) {
  React.useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      setWidth(resolveExpandedWidth(window.innerWidth - e.clientX));
    };
    const handleMouseUp = () => {
      setIsResizing(false);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isResizing, setIsResizing, setWidth]);

  // Collapsing the panel mid-drag unmounts the drawer before any mouseup
  // arrives, which would leave the app with a col-resize cursor, text selection
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
    <>
      <button
        type="button"
        aria-label="Resize expanded panel"
        // Mouse-only affordance, like the docked column's handle: there is no
        // keyboard resize model to expose a focusable control for.
        tabIndex={-1}
        onMouseDown={(e) => {
          e.preventDefault();
          setIsResizing(true);
          document.body.style.cursor = "col-resize";
          document.body.style.userSelect = "none";
        }}
        className="no-drag group absolute inset-y-0 left-1 z-10 flex w-2 cursor-col-resize justify-center border-0 bg-transparent p-0"
      >
        <span
          className={`h-full w-px transition-colors duration-150 ease-out ${
            isResizing
              ? "bg-primary"
              : "bg-transparent delay-100 group-hover:bg-primary"
          }`}
        />
      </button>
      {/* Keeps the col-resize cursor whatever the pointer crosses while dragging
          - content sets its own cursors, and webview tabs would swallow the drag
          entirely. */}
      {isResizing && (
        <div className="fixed inset-0 z-[200] cursor-col-resize" />
      )}
    </>
  );
}
