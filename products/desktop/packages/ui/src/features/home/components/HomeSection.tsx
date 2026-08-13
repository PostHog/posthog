import type { ReactNode } from "react";

/**
 * One block of Home. Every block — the app's own and the canvases stacked below
 * it — wears this frame, which is what lets a column of separate surfaces read
 * as a single page.
 */
export function HomeSection({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3 px-6 py-6">
      <div className="flex items-end justify-between gap-4">
        <div className="flex flex-col gap-0.5">
          <h2 className="font-semibold text-base">{title}</h2>
          {description ? (
            <p className="text-muted-foreground text-xs">{description}</p>
          ) : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
