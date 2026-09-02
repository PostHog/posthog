import { cn } from "@posthog/quill";
import { Link, type LinkProps } from "@tanstack/react-router";
import type { ReactNode } from "react";

/** A section title on the space's context page, with one thing at its right edge. */
export function SpaceSectionHeader({
  title,
  aside,
}: {
  title: string;
  aside?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-(--gray-4) border-b pb-2.5">
      <h2 className="font-semibold text-(--gray-12) text-[15px] tracking-[-0.008em]">
        {title}
      </h2>
      {aside}
    </div>
  );
}

export const SPACE_ROW_ACTION_CLASS =
  "mt-0.5 shrink-0 cursor-pointer rounded-(--radius-2) px-1.5 py-0.5 text-(--gray-10) text-[11.5px] opacity-0 transition-opacity hover:bg-(--gray-4) hover:text-(--gray-12) focus-visible:opacity-100 group-hover:opacity-100 disabled:cursor-default disabled:opacity-50";

/**
 * One row of a list on the space's context page: icon, title, meta, age, and
 * an optional second line. Pages and watches both use it, so the two lists
 * read as one.
 */
export function SpaceRow({
  icon,
  title,
  meta,
  age,
  excerpt,
  action,
  muted = false,
  link,
}: {
  icon: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  age?: string;
  excerpt?: ReactNode;
  /** Shown on hover at the right edge. */
  action?: ReactNode;
  /** Titles of finished things step back in tone. */
  muted?: boolean;
  link: Pick<LinkProps, "to" | "params" | "search">;
}) {
  return (
    <li className="group flex items-start gap-2 rounded-(--radius-2) px-2 py-[7px] transition-colors hover:bg-(--gray-3)">
      <Link
        {...link}
        className="flex min-w-0 flex-1 cursor-pointer items-start gap-2 text-left"
      >
        <span className="mt-[3px] flex w-[14px] shrink-0 justify-center text-(--gray-8) transition-colors group-hover:text-(--gray-11)">
          {icon}
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="flex items-baseline gap-2">
            <span
              className={cn(
                "min-w-0 truncate font-medium text-[14px]",
                muted ? "text-(--gray-10)" : "text-(--gray-12)",
              )}
            >
              {title}
            </span>
            {meta ? (
              <span className="min-w-0 shrink truncate text-(--gray-9) text-[12.5px] tabular-nums">
                {meta}
              </span>
            ) : null}
            <span className="flex-1" />
            <span className="w-12 shrink-0 text-right text-(--gray-9) text-[12.5px] tabular-nums">
              {age ?? "—"}
            </span>
          </span>
          {excerpt ? (
            <span className="block truncate text-(--gray-10) text-[12.5px]">
              {excerpt}
            </span>
          ) : null}
        </span>
      </Link>
      {action}
    </li>
  );
}
