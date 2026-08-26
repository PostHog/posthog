import { CaretDownIcon, type IconProps } from "@phosphor-icons/react";
import { cn } from "@posthog/quill";
import { type ComponentType, type ReactNode, useState } from "react";

export interface DetailSectionProps {
  Icon: ComponentType<IconProps>;
  title: string;
  rightSlot?: ReactNode;
  /**
   * Collapsible header, like the web detail's cards. The title area and the
   * chevron toggle; `rightSlot` stays outside the toggle so interactive
   * controls in it (filter checkboxes, counts with tooltips) keep working.
   */
  collapsible?: boolean;
  defaultCollapsed?: boolean;
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
  collapsible = false,
  defaultCollapsed = false,
  children,
}: DetailSectionProps) {
  const [collapsed, setCollapsed] = useState(collapsible && defaultCollapsed);
  const toggle = () => setCollapsed((current) => !current);
  const open = !(collapsible && collapsed);

  const titleCluster = (
    <>
      <Icon size={14} weight="bold" className="shrink-0 text-gray-11" />
      <span className="truncate font-semibold text-[14px] text-gray-12 tracking-[-0.01em]">
        {title}
      </span>
    </>
  );

  return (
    <section className="flex min-w-0 flex-col rounded-(--radius-2) border border-(--gray-4) bg-(--color-panel-solid)">
      <header
        className={cn(
          "flex select-none items-center gap-3 px-3.5",
          open && "border-(--gray-4) border-b",
          collapsible ? "py-0" : "cursor-default py-2.5",
        )}
      >
        {collapsible ? (
          <button
            type="button"
            onClick={toggle}
            aria-expanded={open}
            className="flex min-w-0 flex-1 items-center gap-2 py-2.5 text-left"
          >
            {titleCluster}
          </button>
        ) : (
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {titleCluster}
          </div>
        )}
        {rightSlot && <div className="shrink-0">{rightSlot}</div>}
        {collapsible && (
          <button
            type="button"
            onClick={toggle}
            aria-expanded={open}
            aria-label={open ? `Collapse ${title}` : `Expand ${title}`}
            className="shrink-0 rounded-(--radius-1) p-1 text-gray-10 hover:bg-(--gray-3) hover:text-gray-12"
          >
            <CaretDownIcon
              size={13}
              className={cn("transition-transform", !open && "-rotate-90")}
            />
          </button>
        )}
      </header>
      {open && <div className="min-w-0 p-3.5">{children}</div>}
    </section>
  );
}
