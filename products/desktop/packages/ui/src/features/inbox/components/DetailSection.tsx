import type { IconProps } from "@phosphor-icons/react";
import type { ComponentType, ReactNode } from "react";

interface DetailSectionProps {
  Icon: ComponentType<IconProps>;
  title: string;
  rightSlot?: ReactNode;
  children: ReactNode;
}

/**
 * Bordered card with a titled header, the shared chrome for every detail-view
 * section (summary, checks, evidence, activity), following the web inbox's
 * card-per-section detail layout.
 */
export function DetailSection({
  Icon,
  title,
  rightSlot,
  children,
}: DetailSectionProps) {
  return (
    <section className="flex min-w-0 flex-col rounded-(--radius-2) border border-(--gray-4) bg-(--color-panel-solid)">
      <header className="flex cursor-default select-none items-center justify-between gap-3 border-(--gray-4) border-b px-3.5 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <Icon size={14} weight="bold" className="shrink-0 text-gray-11" />
          <span className="truncate font-semibold text-[13px] text-gray-12 tracking-[-0.01em]">
            {title}
          </span>
        </div>
        {rightSlot && <div className="shrink-0">{rightSlot}</div>}
      </header>
      <div className="min-w-0 p-3.5">{children}</div>
    </section>
  );
}
