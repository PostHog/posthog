import { CaretDownIcon, CaretRightIcon } from "@phosphor-icons/react";
import { cn, MenuLabel } from "@posthog/quill";
import type { WorkSectionResizer } from "@posthog/ui/features/canvas/hooks/useWorkSectionLayout";
import type { ReactNode, RefCallback } from "react";

function WorkSectionResizeHandle({
  label,
  active,
  resizer,
}: {
  label: string;
  active: boolean;
  resizer: WorkSectionResizer;
}) {
  return (
    <button
      type="button"
      aria-label={`Resize ${label}`}
      title="Drag to resize. Double-click to reset."
      onPointerDown={resizer.onPointerDown}
      onPointerMove={resizer.onPointerMove}
      onPointerUp={resizer.onPointerUp}
      onPointerCancel={resizer.onPointerUp}
      onKeyDown={resizer.onKeyDown}
      onDoubleClick={resizer.onDoubleClick}
      className="group/resize -top-1 absolute inset-x-0 z-10 flex h-2 cursor-row-resize items-center outline-none"
    >
      <span
        className={cn(
          "h-0.5 w-full rounded-full bg-primary opacity-0 transition-opacity group-hover/resize:opacity-100 group-focus-visible/resize:opacity-100",
          active && "opacity-100",
        )}
      />
    </button>
  );
}

export function WorkSection({
  label,
  open,
  count,
  onToggle,
  actions,
  replaceHeading,
  height,
  animate,
  divider,
  resizer,
  resizing = false,
  contentRef,
  children,
}: {
  label: string;
  open: boolean;
  count: number;
  onToggle: () => void;
  actions?: ReactNode;
  replaceHeading?: ReactNode;
  height: number;
  animate: boolean;
  divider: boolean;
  resizer?: WorkSectionResizer;
  resizing?: boolean;
  contentRef: RefCallback<HTMLElement>;
  children: ReactNode;
}) {
  const Caret = open ? CaretDownIcon : CaretRightIcon;
  return (
    <section aria-label={label} className="flex shrink-0 flex-col">
      <div
        className={cn(
          "relative flex h-7 shrink-0 items-center gap-1",
          divider && "border-border border-t",
        )}
      >
        {resizer && (
          <WorkSectionResizeHandle
            label={label}
            active={resizing}
            resizer={resizer}
          />
        )}
        {replaceHeading ?? (
          <MenuLabel
            render={<button type="button" />}
            aria-expanded={open}
            onClick={onToggle}
            className="flex min-w-0 flex-1 items-center gap-1 rounded-sm py-1 font-semibold text-foreground/70 hover:text-foreground"
          >
            {label}
            <Caret size={11} className="shrink-0 opacity-60" />
            {!open && count > 0 && (
              <span className="ml-0.5 font-normal text-muted-foreground tabular-nums">
                {count}
              </span>
            )}
          </MenuLabel>
        )}
        {open && actions && (
          <div className="flex shrink-0 items-center">{actions}</div>
        )}
      </div>
      <div
        style={{ height: open ? height : 0 }}
        className={cn(
          "min-h-0 overflow-hidden",
          animate && "transition-[height] duration-200 ease-out",
        )}
      >
        {open && (
          <div className="scroll-mask-8 h-full scroll-py-8 overflow-y-auto">
            <div ref={contentRef} className="flex flex-col gap-px pb-1">
              {children}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
