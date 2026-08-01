import { Combobox as BaseCombobox } from "@base-ui/react/combobox";
import type { ComponentProps, RefObject } from "react";
import { useRef } from "react";

interface ModalInlineComboboxContentProps
  extends ComponentProps<typeof BaseCombobox.Popup> {
  anchor?: RefObject<Element | null> | Element | null;
  side?: "top" | "bottom" | "left" | "right";
  sideOffset?: number;
  align?: "start" | "center" | "end";
  alignOffset?: number;
}

/**
 * Quill's ComboboxContent portals to document.body. Inside a modal Radix Dialog
 * that puts the search input outside the focus trap. This portals into a local
 * container that stays within the dialog DOM tree instead.
 */
export function ModalInlineComboboxContent({
  className,
  side = "bottom",
  sideOffset = 6,
  align = "start",
  alignOffset = 0,
  anchor,
  children,
  ...popupProps
}: ModalInlineComboboxContentProps) {
  const portalContainerRef = useRef<HTMLDivElement>(null);

  return (
    <>
      <div ref={portalContainerRef} className="relative" />
      <BaseCombobox.Portal container={portalContainerRef}>
        <BaseCombobox.Positioner
          data-quill
          data-quill-portal="popover"
          side={side}
          sideOffset={sideOffset}
          align={align}
          alignOffset={alignOffset}
          anchor={anchor ?? undefined}
          className="isolate z-200"
        >
          <BaseCombobox.Popup
            data-slot="combobox-content"
            className={`quill-combobox__content group/combobox-content ${className ?? ""}`}
            {...popupProps}
          >
            {children}
          </BaseCombobox.Popup>
        </BaseCombobox.Positioner>
      </BaseCombobox.Portal>
    </>
  );
}
