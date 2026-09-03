import {
  type HandleCloseContext,
  type Placement,
  safePolygon,
  useFloating,
} from "@floating-ui/react";
import { type RefObject, useCallback, useEffect, useRef } from "react";

const PREVIEW_TRIGGER_SELECTOR = "[data-channel-preview-trigger]";

type ProtectedTrigger = {
  element: HTMLElement;
  pointerEvents: string;
};

function floatingPlacement(element: HTMLElement): Placement {
  const side = element.dataset.side;
  const align = element.dataset.align;
  if (
    side !== "top" &&
    side !== "right" &&
    side !== "bottom" &&
    side !== "left"
  ) {
    return "right-start";
  }
  return align === "start" || align === "end" ? `${side}-${align}` : side;
}

/**
 * Base UI keeps a PreviewCard open across its gap, but its safe polygon leaves
 * sibling triggers interactive. This blocks those triggers while Floating UI
 * decides whether the pointer is still moving toward the card.
 */
export function ChannelPreviewPointerGrace({
  triggerRef,
  floatingRef,
}: {
  triggerRef: RefObject<HTMLElement | null>;
  floatingRef: RefObject<HTMLElement | null>;
}): null {
  const { context, refs } = useFloating({ placement: "right-start" });
  const contextRef = useRef(context);
  const protectedTriggersRef = useRef<ProtectedTrigger[] | null>(null);
  const mouseMoveHandlerRef = useRef<((event: MouseEvent) => void) | null>(
    null,
  );
  const transitGenerationRef = useRef(0);
  contextRef.current = context;

  const clearProtection = useCallback((): void => {
    transitGenerationRef.current += 1;
    if (mouseMoveHandlerRef.current) {
      document.removeEventListener("mousemove", mouseMoveHandlerRef.current);
      mouseMoveHandlerRef.current = null;
    }
    for (const { element, pointerEvents } of protectedTriggersRef.current ??
      []) {
      element.style.pointerEvents = pointerEvents;
    }
    protectedTriggersRef.current = null;
  }, []);

  const protectTriggers = useCallback((source: HTMLElement): void => {
    if (protectedTriggersRef.current) return;

    const triggers = Array.from(
      document.querySelectorAll<HTMLElement>(PREVIEW_TRIGGER_SELECTOR),
    ).map((element) => ({
      element,
      pointerEvents: element.style.pointerEvents,
    }));
    for (const { element } of triggers) {
      element.style.pointerEvents = element === source ? "auto" : "none";
    }
    protectedTriggersRef.current = triggers;
  }, []);

  useEffect(() => {
    const trigger = triggerRef.current;
    const floating = floatingRef.current;
    if (!trigger || !floating) return;

    refs.setReference(trigger);
    refs.setFloating(floating);

    const handleTriggerEnter = (): void => {
      protectTriggers(trigger);
    };
    const handleTriggerLeave = (event: MouseEvent): void => {
      protectTriggers(trigger);
      if (mouseMoveHandlerRef.current) {
        document.removeEventListener("mousemove", mouseMoveHandlerRef.current);
      }

      const generation = ++transitGenerationRef.current;
      const handleMouseMove = safePolygon()({
        ...contextRef.current,
        x: event.clientX,
        y: event.clientY,
        placement: floatingPlacement(floating),
        elements: {
          reference: trigger,
          domReference: trigger,
          floating,
        },
        onClose: () => {
          if (transitGenerationRef.current === generation) {
            clearProtection();
          }
        },
      } satisfies HandleCloseContext);
      mouseMoveHandlerRef.current = handleMouseMove;
      document.addEventListener("mousemove", handleMouseMove);
      handleMouseMove(event);
    };

    trigger.addEventListener("mouseenter", handleTriggerEnter);
    trigger.addEventListener("mouseleave", handleTriggerLeave);
    floating.addEventListener("mouseenter", clearProtection);
    if (trigger.matches(":hover")) {
      protectTriggers(trigger);
    }

    return () => {
      trigger.removeEventListener("mouseenter", handleTriggerEnter);
      trigger.removeEventListener("mouseleave", handleTriggerLeave);
      floating.removeEventListener("mouseenter", clearProtection);
      clearProtection();
    };
  }, [clearProtection, floatingRef, protectTriggers, refs, triggerRef]);

  return null;
}
