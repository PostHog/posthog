import { inboxReportKeys } from "@posthog/core/inbox/inboxQuery";
import { deriveReportImplementationState } from "@posthog/core/inbox/reportImplementation";
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
import {
  inboxStoryImplementations,
  inboxStoryReport,
} from "@posthog/ui/features/inbox/components/inboxStoryFixtures";
import { useInboxReportReadStore } from "@posthog/ui/features/inbox/stores/inboxReportReadStore";
import { CHANNELS_SIDEBAR_MIN_WIDTH } from "@posthog/ui/features/sidebar/constants";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";
import { expect, waitFor, within } from "storybook/test";
import { useInboxAvailableSuggestedReviewersStore } from "../inboxAvailableSuggestedReviewersStore";
import { useInboxReviewerScopeStore } from "../stores/inboxReviewerScopeStore";
import { useInboxSignalsFilterStore } from "../stores/inboxSignalsFilterStore";
import { InboxStoryData } from "./InboxStoryData";

function WithReadState({
  children,
}: {
  children: ReactNode;
}): React.JSX.Element {
  const queryClient = useQueryClient();
  useEffect(() => {
    const previousAuth = useAuthStore.getState().authState;
    const previousRead = useInboxReportReadStore.getState();
    const previousScope = useInboxReviewerScopeStore.getState();
    const previousFilters = useInboxSignalsFilterStore.getState();
    const previousReviewers =
      useInboxAvailableSuggestedReviewersStore.getState();
    const previousUser = queryClient.getQueryData(authKeys.currentUser("us:1"));
    useInboxReviewerScopeStore.setState({ scope: "for-you" });
    useInboxSignalsFilterStore.getState().resetFilters();
    const reviewers = Array.from({ length: 25 }, (_, index) => ({
      uuid: `reviewer-${index + 1}`,
      name: `Example reviewer ${String(index + 1).padStart(2, "0")}`,
      email: `reviewer${index + 1}@example.com`,
      github_login: `example-reviewer-${index + 1}`,
    }));
    const reviewersKey = inboxReportKeys.availableSuggestedReviewers("us:1:");
    queryClient.setQueryData(reviewersKey, {
      results: reviewers,
      count: reviewers.length,
    });
    useInboxAvailableSuggestedReviewersStore
      .getState()
      .setReviewersForAuthIdentity("us:1", reviewers);
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
      useInboxReportReadStore.setState(previousRead);
      useInboxReviewerScopeStore.setState(previousScope);
      useInboxSignalsFilterStore.setState(previousFilters);
      useInboxAvailableSuggestedReviewersStore.setState(previousReviewers);
      queryClient.removeQueries({ queryKey: reviewersKey, exact: true });
      if (previousUser)
        queryClient.setQueryData(authKeys.currentUser("us:1"), previousUser);
      else
        queryClient.removeQueries({
          queryKey: authKeys.currentUser("us:1"),
          exact: true,
        });
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
      implementationState={deriveReportImplementationState(
        report,
        inboxStoryImplementations.find((entry) => entry.report.id === report.id)
          ?.task,
      )}
      optionValue={report.id}
      isSelected={report.id === "needs-1"}
    />
  );
}

const meta: Meta<typeof InboxPanePresentation> = {
  title: "Inbox/Reports/Sidebar pane",
  component: InboxPanePresentation,
  tags: ["inbox"],
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => (
      <div
        className="h-[760px] border-border border-r bg-chrome"
        style={{ width: CHANNELS_SIDEBAR_MIN_WIDTH }}
      >
        <WithReadState>
          <InboxStoryData>
            <Story />
          </InboxStoryData>
        </WithReadState>
      </div>
    ),
  ],
  render: function SearchablePane(args) {
    const [query, setQuery] = useState(args.query);
    return (
      <InboxPanePresentation
        {...args}
        query={query}
        onQueryChange={setQuery}
        reports={args.reports.filter((report) =>
          `${report.title} ${report.summary}`
            .toLowerCase()
            .includes(query.toLowerCase()),
        )}
      />
    );
  },
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

export const ImplementationProgress: Story = {
  args: {
    reports: [
      reports[0],
      ...inboxStoryImplementations.map((entry) => entry.report),
    ],
  },
};

export const SearchReports: Story = {
  play: async ({ canvas, userEvent }): Promise<void> => {
    await userEvent.type(
      await canvas.findByRole("combobox", { name: "Search reports" }),
      "buffer",
    );
    await expect(
      canvas.getByText("Expose buffer health in the player controls"),
    ).toBeVisible();
    await expect(
      canvas.queryByText("Avoid duplicate evaluations after a reconnect"),
    ).not.toBeInTheDocument();
  },
};

export const ReadAndUnread: Story = {
  play: async ({ canvas, canvasElement, userEvent }): Promise<void> => {
    const unreadButtons = await canvas.findAllByRole("button", {
      name: "Mark report as read",
    });
    const unreadCount = unreadButtons.length;
    await userEvent.click(unreadButtons[0]);
    await expect(
      canvas.getAllByRole("button", { name: "Mark report as read" }),
    ).toHaveLength(unreadCount - 1);
    await userEvent.pointer({
      target: canvas.getByRole("option", {
        name: /keep recurring calculations/i,
      }),
      keys: "[MouseRight]",
    });
    const body = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      await body.findByRole("menuitem", { name: "Mark as unread" }),
    );
    await expect(
      canvas.getAllByRole("button", { name: "Mark report as read" }),
    ).toHaveLength(unreadCount);
  },
};

export const ScopeSearch: Story = {
  play: async ({ canvas, canvasElement, userEvent }): Promise<void> => {
    await userEvent.click(
      await canvas.findByRole("button", { name: "Filter reports" }),
    );
    const body = within(canvasElement.ownerDocument.body);
    await userEvent.hover(await body.findByRole("menuitem", { name: /Scope/ }));
    const search = await body.findByPlaceholderText("Search users…");
    await expect(search).toHaveValue("");
    await expect(await body.findByText("Example reviewer 01")).toBeVisible();
    await expect(
      body.queryByText("Example reviewer 25"),
    ).not.toBeInTheDocument();
    await waitFor(() => expect(search).toBeVisible());
    search.focus();
    await userEvent.type(search, "reviewer25@example.com", { skipClick: true });
    await expect(await body.findByText("Example reviewer 25")).toBeVisible();
  },
};
