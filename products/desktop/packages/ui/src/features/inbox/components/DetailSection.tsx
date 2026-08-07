import type { IconProps } from "@phosphor-icons/react";
import { Flex, Text } from "@radix-ui/themes";
import type { ComponentType, ReactNode } from "react";

interface DetailSectionProps {
  Icon: ComponentType<IconProps>;
  title: string;
  rightSlot?: ReactNode;
  children: ReactNode;
}

export function DetailSection({
  Icon,
  title,
  rightSlot,
  children,
}: DetailSectionProps) {
  return (
    <Flex direction="column" gap="3">
      <Flex
        align="center"
        justify="between"
        gap="3"
        className="min-w-0 cursor-default select-none"
      >
        <Flex align="center" gap="2" className="min-w-0">
          <Icon size={15} weight="bold" className="shrink-0 text-gray-11" />
          <Text className="truncate font-semibold text-[14px] text-gray-12 tracking-[-0.01em]">
            {title}
          </Text>
        </Flex>
        <div className="h-px min-w-4 flex-1 bg-(--gray-5)" />
        {rightSlot && <div className="shrink-0">{rightSlot}</div>}
      </Flex>
      <div>{children}</div>
    </Flex>
  );
}
