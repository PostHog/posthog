import type { IconProps } from "@phosphor-icons/react";
import { Flex, Text } from "@radix-ui/themes";
import type { ComponentType, ReactNode } from "react";

interface RightColumnSectionProps {
  Icon: ComponentType<IconProps>;
  title: string;
  rightSlot?: ReactNode;
  children: ReactNode;
}

/**
 * Slim caption header used by every section in the detail-view right column.
 * Smaller and lighter than `DetailSection` (no spanning divider) so the
 * side column reads as supporting detail rather than competing with the
 * main Summary on the left.
 */
export function RightColumnSection({
  Icon,
  title,
  rightSlot,
  children,
}: RightColumnSectionProps) {
  return (
    <Flex direction="column" gap="2">
      <Flex
        align="center"
        justify="between"
        gap="2"
        className="cursor-default select-none text-gray-10"
      >
        <Flex align="center" gap="2">
          <Icon size={12} className="shrink-0" />
          <Text className="font-medium text-[11px] uppercase tracking-[0.06em]">
            {title}
          </Text>
        </Flex>
        {rightSlot && <div className="shrink-0">{rightSlot}</div>}
      </Flex>
      <div>{children}</div>
    </Flex>
  );
}
