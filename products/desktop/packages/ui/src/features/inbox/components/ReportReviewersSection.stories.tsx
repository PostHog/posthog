import type { SignalReport, SuggestedReviewer } from "@posthog/shared/types";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ReportReviewersSectionView } from "./ReportReviewersSection";

const report: SignalReport = {
  id: "report-1",
  title: "Review request handling",
  summary: "Summary",
  status: "ready",
  total_weight: 1,
  signal_count: 1,
  artefact_count: 1,
  created_at: "2026-08-20T09:00:00Z",
  updated_at: "2026-08-20T09:00:00Z",
};

function reviewer(
  id: string,
  name: string,
  fields: Partial<SuggestedReviewer>,
): SuggestedReviewer {
  return {
    github_login: id,
    github_name: name,
    relevant_commits: [],
    user: {
      id: 1,
      uuid: id,
      first_name: name,
      last_name: "",
      email: `${id}@example.com`,
    },
    ...fields,
  };
}

const sharedReason = "Maintains request handling and retry behavior.";

const meta: Meta<typeof ReportReviewersSectionView> = {
  title: "Inbox/Reports/Suggested reviewers section",
  component: ReportReviewersSectionView,
  parameters: { layout: "centered" },
  decorators: [
    (Story) => (
      <div className="w-[22rem]">
        <Story />
      </div>
    ),
  ],
  args: { report, disabled: false, onRemove: () => undefined },
};

export default meta;
type Story = StoryObj<typeof ReportReviewersSectionView>;

const groupedReviewers: SuggestedReviewer[] = [
  reviewer("avery", "Avery Chen", {
    reason: sharedReason,
    explanation: sharedReason,
    source_skill: "signals-scout-runtime-ownership",
    source_label: "Runtime ownership scout",
  }),
  reviewer("jordan", "Jordan Lee", {
    reason: sharedReason,
    explanation: sharedReason,
    source_skill: "signals-scout-runtime-ownership",
    source_label: "Runtime ownership scout",
  }),
  reviewer("rowan", "Rowan Patel", {
    explanation: "Recently changed the affected transport.",
    source_label: "Code history",
  }),
];

const withTeammateReviewers: SuggestedReviewer[] = [
  ...groupedReviewers,
  reviewer("quinn", "Quinn Foster", {
    source_skill: null,
    source_label: "Added by teammate",
    reason: "Added as a reviewer by Avery Chen on Jan 1, 2026",
    explanation: null,
  }),
];

export const GroupedReviewers: Story = {
  args: { reviewers: groupedReviewers },
};

export const AddedByTeammate: Story = {
  args: { reviewers: withTeammateReviewers },
};

export const AddedByFullName: Story = {
  args: {
    reviewers: withTeammateReviewers.map((reviewer) =>
      reviewer.github_login === "quinn"
        ? { ...reviewer, explanation: "Added by Avery Chen" }
        : reviewer,
    ),
  },
};
