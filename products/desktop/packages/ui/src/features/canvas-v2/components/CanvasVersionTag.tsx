import type { ReactElement } from "react";

export function CanvasVersionTag(): ReactElement {
  return (
    <span className="shrink-0 rounded-sm bg-fill-hover px-1 py-px font-medium text-[10px] text-muted-foreground leading-none">
      v2
    </span>
  );
}
