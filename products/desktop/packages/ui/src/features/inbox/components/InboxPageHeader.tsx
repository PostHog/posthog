import {
  type InboxTabCounts,
  inboxScopeApplies,
  inboxTabFromPath,
} from "@posthog/core/inbox/reportMembership";
import { useBluebirdFlag } from "@posthog/ui/features/feature-flags/useBluebirdFlag";
import { InboxScopeSelect } from "@posthog/ui/features/inbox/components/InboxScopeSelect";
import {
  InboxTabBar,
  InboxTabs,
} from "@posthog/ui/features/inbox/components/InboxTabBar";
import {
  PageHeader,
  PageHeaderDescription,
  PageHeaderFilters,
  PageHeaderHeading,
  PageHeaderNav,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import { Flex, Text } from "@radix-ui/themes";
import { useRouterState } from "@tanstack/react-router";

interface InboxPageHeaderProps {
  counts: InboxTabCounts;
}

export function InboxPageHeader({ counts }: InboxPageHeaderProps) {
  // The shared page header ships behind bluebird; everyone else keeps the
  // header this page has always had. Delete the legacy branch when the flag
  // graduates.
  const bluebird = useBluebirdFlag();
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  if (!bluebird) return <LegacyInboxPageHeader counts={counts} />;

  return (
    <PageHeader>
      <PageHeaderHeading>
        <PageHeaderTitleRow>
          <PageHeaderTitle>Inbox</PageHeaderTitle>
        </PageHeaderTitleRow>
        <PageHeaderDescription>
          Work done by your agents – pull requests, reports, and live runs.
        </PageHeaderDescription>
      </PageHeaderHeading>
      <PageHeaderNav>
        <InboxTabs counts={counts} />
        {inboxScopeApplies(inboxTabFromPath(pathname)) && (
          <PageHeaderFilters>
            <InboxScopeSelect />
          </PageHeaderFilters>
        )}
      </PageHeaderNav>
    </PageHeader>
  );
}

function LegacyInboxPageHeader({ counts }: InboxPageHeaderProps) {
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
