import { RobotIcon } from "@phosphor-icons/react";
import {
  type InboxTabCounts,
  inboxScopeApplies,
  inboxTabFromPath,
} from "@posthog/core/inbox/reportMembership";
import { Button } from "@posthog/quill";
import { useBluebirdFlag } from "@posthog/ui/features/feature-flags/useBluebirdFlag";
import { InboxScopeSelect } from "@posthog/ui/features/inbox/components/InboxScopeSelect";
import {
  InboxTabBar,
  InboxTabs,
} from "@posthog/ui/features/inbox/components/InboxTabBar";
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderDescription,
  PageHeaderFilters,
  PageHeaderHeading,
  PageHeaderNav,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import { Link, useRouterState } from "@tanstack/react-router";

interface InboxPageHeaderProps {
  counts: InboxTabCounts;
}

/**
 * Responder configuration lives at /agents, not in the inbox. The header
 * carries this always-visible way there so the config surface stays one click
 * away from the work it powers.
 */
function ConfigureAgentsButton() {
  return (
    <Button
      variant="primary"
      size="sm"
      render={<Link to="/agents" />}
      className="shrink-0"
    >
      <RobotIcon size={14} />
      Configure agents
    </Button>
  );
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
          <PageHeaderTitle>Self-driving</PageHeaderTitle>
          <PageHeaderActions>
            <ConfigureAgentsButton />
          </PageHeaderActions>
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
    <div className="flex shrink-0 flex-col gap-3 border-(--gray-5) border-b px-6 pt-5 pb-0">
      <div className="flex items-start justify-between gap-3">
        <div className="flex cursor-default select-none flex-col gap-0.5">
          <span className="font-bold text-[22px] text-gray-12 leading-tight tracking-tight">
            Self-driving
          </span>
          <span className="max-w-3xl text-[12.5px] text-gray-11 leading-snug">
            Work done by your agents – pull requests, reports, and live runs.
          </span>
        </div>
        <ConfigureAgentsButton />
      </div>
      <InboxTabBar counts={counts} />
    </div>
  );
}
