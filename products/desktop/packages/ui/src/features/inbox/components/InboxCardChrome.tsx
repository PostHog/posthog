import { cn } from "@posthog/quill";
import type { ReactNode } from "react";

/**
 * Shared layout chrome for inbox list cards, following the web inbox's
 * unified ReportCard: one column at narrow container widths, a
 * [body | actions rail] row from `@lg` up. Requires an `@container` ancestor,
 * which the list shells own. The card root is `relative` so the timestamp and
 * top-right badge slots can pin to its corners in the row layout.
 */
export function inboxCardClassName(options: {
  dashed?: boolean;
  isSelected?: boolean;
  dimmed?: boolean;
}): string {
  return cn(
    "group relative flex w-full flex-col gap-2.5 @lg:flex-row @lg:items-stretch @lg:gap-3",
    "rounded-(--radius-2) border bg-(--color-panel-solid) px-4 py-3.5 transition duration-150 hover:bg-(--gray-2)",
    options.dashed
      ? "border-(--gray-6) border-dashed hover:border-(--gray-7)"
      : "border-border hover:border-(--gray-6) hover:shadow-sm",
    options.dimmed && "opacity-90",
    options.isSelected &&
      "border-(--accent-8) bg-(--accent-2) ring-(--accent-8) ring-2 ring-inset",
  );
}

export const inboxCardBodyClassName =
  "flex min-w-0 flex-1 items-start gap-3 text-left text-inherit no-underline focus-visible:outline-none";

/**
 * Actions rail. In the column layout it is a plain right-aligned row under
 * the body; from `@lg` it stretches beside the body and gains the left
 * divider, so the border never renders as a floating rule above stacked
 * content.
 */
export function InboxCardActions({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-end gap-2.5 @lg:self-stretch border-border @lg:border-l @lg:pl-3",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function InboxCardTopRight({ children }: { children: ReactNode }) {
  return <div className="absolute top-3.5 right-4 z-10">{children}</div>;
}

/**
 * Last-updated stamp: in flow at the end of the body in the column layout,
 * pinned to the card's bottom-right corner from `@lg`.
 */
export function InboxCardTimestamp({
  timestamp,
  label,
}: {
  timestamp: string | null | undefined;
  label?: string;
}) {
  const date = timestamp ? new Date(timestamp) : null;
  if (!date || Number.isNaN(date.getTime())) {
    return null;
  }
  const formatted = date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
  return (
    <div className="@lg:absolute @lg:right-4 @lg:bottom-3 @lg:z-10 @lg:mt-0 mt-0.5">
      <span
        className="text-[12px] text-gray-10 tabular-nums"
        title={label ?? "Last updated"}
      >
        {formatted}
      </span>
    </div>
  );
}
