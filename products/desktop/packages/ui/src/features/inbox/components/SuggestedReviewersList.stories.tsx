import type { SuggestedReviewer } from "@posthog/shared/types";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { SuggestedReviewersList } from "./SuggestedReviewersList";

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

const sharedReason = "These reviewers maintain the request execution parser.";

const sharedReasonReviewers: SuggestedReviewer[] = [
  ["avery", "Avery Chen"],
  ["jordan", "Jordan Lee"],
  ["rowan", "Rowan Patel"],
  ["casey", "Casey Morgan"],
  ["taylor", "Taylor Brooks"],
  ["morgan", "Morgan Reed"],
  ["riley", "Riley Davis"],
  ["devon", "Devon Clark"],
].map(([id, name]) =>
  reviewer(id, name, {
    source_skill: "signals-scout-runtime-ownership",
    source_label: "Runtime ownership scout",
    explanation: sharedReason,
    reason: sharedReason,
  }),
);

const longReason =
  "These reviewers maintain the request parser and retry handling. Review the long configuration path before release because it affects several report views.";

const longReasonReviewers: SuggestedReviewer[] = [
  ["casey", "Casey Morgan"],
  ["jamie", "Jamie Kim"],
].map(([id, name]) =>
  reviewer(id, name, {
    source_skill: "signals-scout-agent-feedback",
    source_label: "Agent feedback scout",
    explanation: longReason,
  }),
);

const meta: Meta<typeof SuggestedReviewersList> = {
  title: "Inbox/Reports/Suggested reviewers",
  component: SuggestedReviewersList,
  tags: ["inbox"],
  parameters: { layout: "centered" },
  decorators: [
    (Story, context) => (
      <div
        className="rounded-sm border border-border bg-card p-3.5"
        style={{ width: context.parameters.panelWidth ?? "46rem" }}
      >
        <Story />
      </div>
    ),
  ],
  args: {
    disabled: false,
    onRemove: () => undefined,
  },
};

export default meta;
type Story = StoryObj<typeof SuggestedReviewersList>;

export const CodeHistory: Story = {
  args: {
    reviewers: [
      reviewer("maya", "Maya Rivera", {
        source_label: "Code history",
        explanation: "Changed the checkout handler where this issue occurs.",
      }),
      reviewer("theo", "Theo Brooks", {
        source_label: "Code history",
        explanation: "Built the retry path used by this request.",
      }),
      reviewer("nina", "Nina Park", {
        source_label: "Code history",
        explanation: "Recently changed the affected transport.",
      }),
    ],
  },
};

export const SharedReason: Story = {
  args: { reviewers: sharedReasonReviewers },
};

export const NarrowPanel: Story = {
  parameters: { panelWidth: "26rem" },
  args: {
    reviewers: [
      reviewer("unlinked", "Unlinked author", {
        user: null,
        source_label: "Code history",
        explanation:
          "Changed example.com/services/request-processing/a-very-long-path-without-spaces/or-identifiers.",
      }),
      reviewer("solo", "Solo Scout", {
        source_skill: "signals-scout-infrastructure-reliability",
        source_label:
          "Infrastructure reliability and request processing ownership scout",
        explanation: "Maintains the request path.",
      }),
      ...sharedReasonReviewers.slice(0, 2),
    ],
  },
};

export const WidePanelLongReason: Story = {
  args: { reviewers: longReasonReviewers },
};

export const NarrowPanelLongReason: Story = {
  parameters: { panelWidth: "26rem" },
  args: { reviewers: longReasonReviewers },
};
