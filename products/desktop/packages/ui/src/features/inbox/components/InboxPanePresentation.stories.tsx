import { Button } from "@posthog/quill";
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
    implementation_pr_url: "https://github.com/PostHog/posthog/pull/12345",
  }),
  inboxStoryReport({
    id: "needs-1",
    title: "feat(replay): expose buffer health in the player controls",
    priority: "P2",
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
    (Story) => (
      <div
        className="h-[760px] border-border border-r bg-chrome"
        style={{ width: CHANNELS_SIDEBAR_MIN_WIDTH }}
      >
        <WithReadState>
          <Story />
        </WithReadState>
      </div>
    ),
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
