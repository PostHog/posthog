import type { ReactNode } from "react";

export function SideColumnHeading({ children }: { children: ReactNode }) {
  return (
    <h2 className="sticky top-0 z-10 bg-gray-1 px-3.5 pt-4 pb-1.5 font-semibold text-[11px] text-foreground/70 uppercase tracking-wider">
      {children}
    </h2>
  );
}
