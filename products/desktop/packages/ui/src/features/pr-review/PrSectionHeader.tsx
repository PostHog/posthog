import type { IconProps } from "@phosphor-icons/react";
import { CaretDownIcon } from "@phosphor-icons/react";
import { Text } from "@radix-ui/themes";
import type { ComponentType, ReactNode } from "react";

/**
 * Clickable section header matching the DetailSection chrome, for the
 * collapsible PR sections (checks, comments). The right slot stays visible
 * while collapsed so it can carry a summary.
 */
export function PrSectionHeader({
  Icon,
  title,
  collapsed,
  onToggle,
  summary,
}: {
  Icon: ComponentType<IconProps>;
  title: string;
  collapsed: boolean;
  onToggle: () => void;
  summary?: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex w-full min-w-0 cursor-pointer items-center gap-3 border-0 bg-transparent p-0 text-left"
    >
      <span className="flex min-w-0 items-center gap-2">
        <Icon size={15} weight="bold" className="shrink-0 text-gray-11" />
        <Text className="truncate font-semibold text-[14px] text-gray-12 tracking-[-0.01em]">
          {title}
        </Text>
      </span>
      <div className="h-px min-w-4 flex-1 bg-(--gray-5)" />
      <span className="flex shrink-0 items-center gap-2">
        {summary}
        <CaretDownIcon
          size={12}
          className="text-(--gray-9)"
          style={{
            transform: collapsed ? "rotate(-90deg)" : "rotate(0deg)",
            transition: "transform 0.15s",
          }}
        />
      </span>
    </button>
  );
}
