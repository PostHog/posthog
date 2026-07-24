import type { InboxTabCounts } from "@posthog/core/inbox/reportMembership";
import { InboxTabBar } from "@posthog/ui/features/inbox/components/InboxTabBar";
import { Flex, Text } from "@radix-ui/themes";

interface InboxPageHeaderProps {
  counts: InboxTabCounts;
}

export function InboxPageHeader({ counts }: InboxPageHeaderProps) {
  return (
    <Flex
      direction="column"
      gap="3"
      className="shrink-0 border-(--gray-5) border-b px-6 pt-5 pb-0"
    >
      <Flex direction="column" gap="0.5" className="cursor-default select-none">
        <Text className="font-bold text-[22px] text-gray-12 leading-tight tracking-tight">
          Inbox
        </Text>
        <Text className="max-w-3xl text-[12.5px] text-gray-11 leading-snug">
          Work done by your agents – pull requests, reports, and live runs.
        </Text>
      </Flex>
      <InboxTabBar counts={counts} />
    </Flex>
  );
}
