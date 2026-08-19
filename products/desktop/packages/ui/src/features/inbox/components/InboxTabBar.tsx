import {
  INBOX_TAB_KEYS,
  INBOX_TAB_LABEL,
  INBOX_TAB_LIST_ROUTE,
  type InboxTabCounts,
  type InboxTabKey,
  inboxScopeApplies,
  inboxTabFromPath,
} from "@posthog/core/inbox/reportMembership";
import { Tabs, TabsList, TabsTrigger } from "@posthog/quill";
import { InboxScopeSelect } from "@posthog/ui/features/inbox/components/InboxScopeSelect";
import { useNavigate, useRouterState } from "@tanstack/react-router";

interface InboxTabBarProps {
  counts: InboxTabCounts;
}

/** The legacy header's row: tabs with the reviewer-scope select alongside. */
export function InboxTabBar({ counts }: InboxTabBarProps) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const activeKey = inboxTabFromPath(pathname);

  return (
    <div className="flex min-w-0 items-center justify-between gap-2">
      <InboxTabs counts={counts} />
      {inboxScopeApplies(activeKey) && <InboxScopeSelect />}
    </div>
  );
}

/** Just the tab strip — the header slots its own filters beside it. */
export function InboxTabs({ counts }: InboxTabBarProps) {
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const activeKey = inboxTabFromPath(pathname);

  // quill's TabsList is `inline-flex w-fit` with no wrap or scroll of its own,
  // so at narrow widths the strip needs a scroll container or it overflows the
  // header row.
  return (
    <Tabs
      value={activeKey}
      className="min-w-0 overflow-x-auto"
      onValueChange={(value: string) => {
        const key = value as InboxTabKey;
        navigate({ to: INBOX_TAB_LIST_ROUTE[key] });
      }}
    >
      <TabsList
        variant="line"
        className="h-auto gap-0.5 [&_.quill-tabs__indicator]:transition-[transform,width]! [&_.quill-tabs__indicator]:duration-100! [&_.quill-tabs__indicator]:ease-out!"
      >
        {INBOX_TAB_KEYS.map((key) => {
          const isActive = key === activeKey;
          return (
            <TabsTrigger key={key} value={key} className="gap-1.5 px-2.5 py-2">
              <span className="font-medium text-[13px]">
                {INBOX_TAB_LABEL[key]}
              </span>
              {/* Runs and the open-ended Archive don't get a running total — it adds no signal. */}
              {key !== "runs" && key !== "dismissed" && counts[key] > 0 && (
                <span
                  className={
                    isActive
                      ? "text-[12px] text-gray-11 tabular-nums"
                      : "text-[12px] text-gray-10 tabular-nums"
                  }
                >
                  {counts[key]}
                </span>
              )}
            </TabsTrigger>
          );
        })}
      </TabsList>
    </Tabs>
  );
}
