import { Button, cn } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import {
  ANONYMOUS_AUTH_STATE,
  useAuthStore,
} from "@posthog/ui/features/auth/store";
import { authKeys } from "@posthog/ui/features/auth/useCurrentUser";
import { InboxFilterMenu } from "@posthog/ui/features/inbox/components/InboxFilterMenu";
import { InboxPanePresentation } from "@posthog/ui/features/inbox/components/InboxPanePresentation";
import { InboxPaneRow } from "@posthog/ui/features/inbox/components/InboxPaneRow";
import { inboxStoryReport } from "@posthog/ui/features/inbox/components/inboxStoryFixtures";
import { useInboxReportReadStore } from "@posthog/ui/features/inbox/stores/inboxReportReadStore";
import { RAIL_CONTAINER_CLASS } from "@posthog/ui/features/sidebar/components/RailListItem";
import { CHANNELS_SIDEBAR_MIN_WIDTH } from "@posthog/ui/features/sidebar/constants";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect } from "react";

function WithReadState({
  children,
}: {
  children: ReactNode;
}): React.JSX.Element {
  const queryClient = useQueryClient();
  useEffect(() => {
    const previousAuth = useAuthStore.getState().authState;
    queryClient.setQueryData(authKeys.currentUser("us:1"), {
      uuid: "storybook-reader",
    });
    useAuthStore.setState({
      authState: {
        ...ANONYMOUS_AUTH_STATE,
        status: "authenticated",
        cloudRegion: "us",
        currentProjectId: 1,
      },
    });
    useInboxReportReadStore.setState({
      readByKey: {
        [JSON.stringify(["us:1", "storybook-reader", "needs-1"])]: true,
      },
      hasHydrated: true,
    });
    return () => {
      useAuthStore.setState({ authState: previousAuth });
    };
  }, [queryClient]);
  return <>{children}</>;
}

const reports = [
  inboxStoryReport({
    id: "review-1",
    title: "fix(cohorts): keep recurring calculations within their budget",
    summary:
      "Recurring cohort calculations can overlap after a delayed run, which increases queue time for later updates. The next scheduled run can start before the first has finished. This leaves users with stale cohort membership until the queue catches up.",
    implementation_pr_url: "https://github.com/PostHog/posthog/pull/12345",
    implementation_pr_state: "draft",
  }),
  inboxStoryReport({
    id: "needs-1",
    title: "feat(replay): expose buffer health in the player controls",
    priority: "P2",
    implementation_pr_url: null,
  }),
  inboxStoryReport({
    id: "needs-2",
    title: "fix(flags): avoid duplicate evaluations after a reconnect",
    priority: "P0",
  }),
  inboxStoryReport({
    id: "needs-3",
    title:
      "feat(insights): preserve breakdown order in saved results so a shared link opens the way it was left",
    priority: "P3",
  }),
  inboxStoryReport({
    id: "resolved-1",
    status: "resolved",
    title: "fix(webhooks): retry delivery after a transient timeout",
    priority: "P2",
    implementation_pr_url: "https://github.com/PostHog/posthog/pull/12346",
    implementation_pr_merged: true,
  }),
];

function paneRow(report: SignalReport): React.JSX.Element {
  return (
    <InboxPaneRow
      key={report.id}
      report={report}
      optionValue={report.id}
      isSelected={report.id === "needs-1"}
    />
  );
}

const meta: Meta<typeof InboxPanePresentation> = {
  title: "Inbox/Reports/Sidebar pane",
  component: InboxPanePresentation,
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story, context) => {
      const railWidth =
        typeof context.parameters.railWidth === "number"
          ? context.parameters.railWidth
          : CHANNELS_SIDEBAR_MIN_WIDTH;
      return (
        <div
          className={cn(
            RAIL_CONTAINER_CLASS,
            "h-[760px] border-border border-r bg-chrome",
          )}
          style={{ width: railWidth }}
        >
          <WithReadState>
            <Story />
          </WithReadState>
        </div>
      );
    },
  ],
  args: {
    reports,
    query: "",
    isLoading: false,
    isFetchingNextPage: false,
    hasNextPage: false,
    hasActiveFilters: false,
    oldestFirst: false,
    filterControl: (
      <>
        <Button variant="outline" size="sm">
          Triage mode
        </Button>
        <InboxFilterMenu active={false} onClearFilters={() => {}} />
      </>
    ),
    renderReport: paneRow,
    onQueryChange: () => {},
    onClearFilters: () => {},
    onLoadMore: () => {},
    className: "h-full",
  },
};

export default meta;
type Story = StoryObj<typeof InboxPanePresentation>;

export const ReportList: Story = {};

export const ReportListAt400px: Story = {
  parameters: { railWidth: 400 },
};

export const ReportListAt560px: Story = {
  parameters: { railWidth: 560 },
};

export const NothingToReview: Story = {
  args: { reports: [] },
};

export const NoSearchMatches: Story = {
  args: { reports: [], query: "checkout" },
};

export const FiltersActive: Story = {
  args: {
    hasActiveFilters: true,
    filterControl: <InboxFilterMenu active onClearFilters={() => {}} />,
  },
};
