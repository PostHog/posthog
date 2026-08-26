import { Flex, Text } from "@radix-ui/themes";
import type { ReactNode } from "react";

interface SettingsSubsectionProps {
  title: string;
  description?: ReactNode;
  /** Optional trailing control, right-aligned with the title. */
  actions?: ReactNode;
  children: ReactNode;
}

/**
 * Section header shared by the settings pages that group content into blocks
 * rather than rows of controls (Agents, Plan & usage), so every page keeps the
 * same heading scale and divider rhythm.
 */
export function SettingsSubsection({
  title,
  description,
  actions,
  children,
}: SettingsSubsectionProps) {
  return (
    <Flex
      direction="column"
      gap="4"
      className="border-(--gray-5) border-t pt-8 first:border-t-0 first:pt-0"
    >
      <Flex align="start" justify="between" gap="4" wrap="wrap">
        <Flex direction="column" gap="1">
          <Flex align="center" gap="2" wrap="wrap">
            <Text className="font-semibold text-[13px] text-gray-12">
              {title}
            </Text>
          </Flex>
          {description ? (
            <Text className="max-w-2xl text-[12.5px] text-gray-11 leading-snug">
              {description}
            </Text>
          ) : null}
        </Flex>
        {actions ? <div className="shrink-0">{actions}</div> : null}
      </Flex>
      {children}
    </Flex>
  );
}
