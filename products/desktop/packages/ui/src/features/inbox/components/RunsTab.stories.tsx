import { inboxReportKeys } from "@posthog/core/inbox/inboxQuery";
import {
  buildArchiveListOrdering,
  INBOX_PIPELINE_STATUS_FILTER,
} from "@posthog/core/inbox/reportFiltering";
import { inboxStoryReport } from "@posthog/ui/features/inbox/components/inboxStoryFixtures";
import { RunsTab } from "@posthog/ui/features/inbox/components/RunsTab";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";

const reports = [
  inboxStoryReport({
    id: "run-queued",
    title: "fix(flags): avoid duplicate evaluations after a reconnect",
    status: "candidate",
    updated_at: "2026-08-28T11:00:00Z",
  }),
  inboxStoryReport({
    id: "run-completed",
    title: "fix(replay): show buffer health in the player",
    status: "ready",
    updated_at: "2026-08-28T14:00:00Z",
  }),
  inboxStoryReport({
    id: "run-live",
    title: "fix(cohorts): prevent overlapping calculations",
    status: "in_progress",
    updated_at: "2026-08-28T13:00:00Z",
  }),
  inboxStoryReport({
    id: "run-failed",
    title: "fix(webhooks): retry delivery after a timeout",
    status: "failed",
    updated_at: "2026-08-28T12:00:00Z",
  }),
];

function WithRuns({ children }: { children: ReactNode }): ReactNode {
  const queryClient = useQueryClient();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const queryKey = inboxReportKeys.infiniteList({
      status: INBOX_PIPELINE_STATUS_FILTER,
      ordering: buildArchiveListOrdering("updated_at", "desc"),
      limit: 50,
    });
    const previousData = queryClient.getQueryData(queryKey);
    queryClient.setQueryData(queryKey, {
      pages: [{ results: reports, count: reports.length }],
      pageParams: [0],
    });
    setReady(true);
    return () => {
      if (previousData === undefined) {
        queryClient.removeQueries({ queryKey, exact: true });
      } else {
        queryClient.setQueryData(queryKey, previousData);
      }
    };
  }, [queryClient]);
  return ready ? children : null;
}

const meta: Meta<typeof RunsTab> = {
  title: "Inbox/Runs",
  component: RunsTab,
  tags: ["inbox"],
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => (
      <WithRuns>
        <Story />
      </WithRuns>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof RunsTab>;

export const MixedStates: Story = {};

export const Narrow: Story = {
  decorators: [
    (Story) => (
      <div className="w-[520px]">
        <Story />
      </div>
    ),
  ],
};
