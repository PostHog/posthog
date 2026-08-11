import { Robot } from "@phosphor-icons/react";
import type { Adapter } from "@posthog/shared";
import { Flex, Text } from "@radix-ui/themes";

interface AdapterIndicatorProps {
  adapter: Adapter;
}

export function AdapterIndicator({ adapter }: AdapterIndicatorProps) {
  return (
    <Flex align="center" gap="1">
      <Robot size={12} weight="duotone" className="text-(--gray-9)" />
      <Text className="font-mono text-(--gray-9) text-[13px]">{adapter}</Text>
    </Flex>
  );
}
