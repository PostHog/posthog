import {
  INBOX_TAB_KEYS,
  INBOX_TAB_LABEL,
  INBOX_TAB_LIST_ROUTE,
  type InboxTabCounts,
  type InboxTabKey,
} from "@posthog/core/inbox/reportMembership";
import { Tabs, TabsList, TabsTrigger } from "@posthog/quill";
import { InboxScopeSelect } from "@posthog/ui/features/inbox/components/InboxScopeSelect";
import { Flex } from "@radix-ui/themes";
import { useNavigate, useRouterState } from "@tanstack/react-router";

interface InboxTabBarProps {
  counts: InboxTabCounts;
}

function activeTabFromPath(pathname: string): InboxTabKey {
  if (pathname.startsWith(INBOX_TAB_LIST_ROUTE.reports)) return "reports";
  if (pathname.startsWith(INBOX_TAB_LIST_ROUTE.runs)) return "runs";
  if (pathname.startsWith(INBOX_TAB_LIST_ROUTE.dismissed)) return "dismissed";
  return "pulls";
}

export function InboxTabBar({ counts }: InboxTabBarProps) {
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const activeKey = activeTabFromPath(pathname);

  return (
    <Flex align="center" justify="between" className="min-w-0">
      <Tabs
        value={activeKey}
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
              <TabsTrigger
                key={key}
                value={key}
                className="gap-1.5 px-2.5 py-2"
              >
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
      {activeKey !== "runs" && activeKey !== "dismissed" && (
        <InboxScopeSelect />
      )}
    </Flex>
  );
}
