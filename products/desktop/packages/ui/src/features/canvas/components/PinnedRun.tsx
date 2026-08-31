import { cn, MenuLabel } from "@posthog/quill";
import type { ReactNode, RefObject } from "react";

export function PinnedRun({
  dropRef,
  dragging,
  highlight,
  hasItems,
  children,
}: {
  dropRef: RefObject<HTMLDivElement | null>;
  dragging: boolean;
  highlight: boolean;
  hasItems: boolean;
  children: ReactNode;
}) {
  return (
    <div
      ref={dropRef}
      className={cn(
        "flex min-h-0 flex-col gap-px rounded-md transition-[min-height,background-color] duration-150 ease-out motion-reduce:transition-none",
        dragging && "min-h-[100px]",
        highlight && "bg-accent-2 ring-1 ring-accent-6",
      )}
    >
      <div
        className={cn(
          "grid transition-[grid-template-rows] duration-150 ease-out motion-reduce:transition-none",
          hasItems || dragging ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
        )}
      >
        <div className="overflow-hidden">
          <MenuLabel>Pinned</MenuLabel>
        </div>
      </div>
      {children}
    </div>
  );
}
