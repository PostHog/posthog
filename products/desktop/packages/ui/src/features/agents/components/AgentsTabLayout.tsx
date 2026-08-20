import { RobotIcon } from "@phosphor-icons/react";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { Flex, Text } from "@radix-ui/themes";
import { type ReactNode, useMemo } from "react";

export function AgentsTabLayout({ children }: { children: ReactNode }) {
  const headerContent = useMemo(
    () => (
      <Flex align="center" gap="2" className="w-full min-w-0">
        <RobotIcon size={12} className="shrink-0 text-gray-10" />
        <Text
          className="truncate whitespace-nowrap font-medium text-[13px]"
          title="Agents"
        >
          Agents
        </Text>
      </Flex>
    ),
    [],
  );
  useSetHeaderContent(headerContent);

  return (
    <Flex direction="column" className="h-full min-h-0">
      <div className="cursor-default select-none border-(--gray-5) border-b px-6 py-5">
        <Flex direction="column" gap="0.5">
          <Text className="font-bold text-[22px] text-gray-12 leading-tight tracking-tight">
            Agents
          </Text>
          <Text className="max-w-3xl text-[12.5px] text-gray-11 leading-snug">
            Self-driving agents that watch your project and surface work for
            review.
          </Text>
        </Flex>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto max-w-4xl px-6 py-6">{children}</div>
      </div>
    </Flex>
  );
}
