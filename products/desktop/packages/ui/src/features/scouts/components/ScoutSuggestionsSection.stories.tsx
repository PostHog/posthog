import type {
  ScoutSuggestionItem,
  ScoutSuggestionSet,
} from "@posthog/api-client/posthog-client";
import type { Meta, StoryObj } from "@storybook/react-vite";
import type { ScoutSuggestionActions } from "../hooks/useScoutSuggestionActions";
import { ScoutSuggestionsSectionView } from "./ScoutSuggestionsSection";

const item = (
  overrides: Partial<ScoutSuggestionItem> = {},
): ScoutSuggestionItem => ({
  id: "suggestion-1",
  kind: "custom",
  skill_name: "signals-scout-checkout-funnel",
  title: "Watch the checkout funnel for drop-off",
  why_here:
    "Checkout conversion moved twice last month, and the funnel insight on your revenue dashboard is the one people open most.",
  description: "Investigates conversion through the checkout funnel.",
  draft_body:
    "# Checkout funnel\n\nCompare this week's checkout conversion with the four weeks before it. Report a drop of more than 5 points.",
  proposed_config: {
    run_cron_schedule: "0 9 * * 1",
    run_interval_minutes: null,
    emit: true,
  },
  gap: true,
  confidence: "high",
  ...overrides,
});

const ITEMS = [
  item(),
  item({
    id: "suggestion-2",
    kind: "canonical",
    skill_name: "signals-scout-error-tracking",
    title: "Sweep error tracking for new and spiking issues",
    why_here:
      "Two of your top issues reopened this week, and nothing in the fleet watches error tracking.",
    description: "",
    draft_body: "",
    gap: false,
    confidence: "medium",
    proposed_config: {
      run_cron_schedule: null,
      run_interval_minutes: 360,
      emit: true,
    },
  }),
  item({
    id: "suggestion-3",
    title: "Watch signup activation week over week",
    why_here:
      "Signups grew 30% this month while activation stayed flat, so the two are worth watching together.",
    gap: false,
    confidence: "low",
    proposed_config: {
      run_cron_schedule: null,
      run_interval_minutes: null,
      emit: false,
    },
  }),
];

const SET: ScoutSuggestionSet = {
  status: "fresh",
  generated_at: new Date(Date.now() - 3 * 3_600_000).toISOString(),
  model: "",
  fleet_snapshot: [],
  items: ITEMS,
};

const ACTIONS: ScoutSuggestionActions = {
  hiddenIds: [],
  busyIds: [],
  isScanning: false,
  dismiss: async () => undefined,
  activate: async () => undefined,
  refresh: async () => undefined,
};

const meta: Meta<typeof ScoutSuggestionsSectionView> = {
  title: "Scouts/ScoutSuggestionsSection",
  component: ScoutSuggestionsSectionView,
  args: {
    items: ITEMS,
    suggestionSet: SET,
    isLoading: false,
    surface: "strip",
    actions: ACTIONS,
  },
  decorators: [
    (Story) => (
      <div className="w-[900px] p-4">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof ScoutSuggestionsSectionView>;

export const Default: Story = {};

/** One pick left keeps a single narrow column rather than stretching across the row. */
export const SingleSuggestion: Story = {
  args: { items: [ITEMS[0]], suggestionSet: { ...SET, items: [ITEMS[0]] } },
};

/** The fleet moved on since the batch was picked, so the picks carry a caveat. */
export const StaleBatch: Story = {
  args: { suggestionSet: { ...SET, status: "stale" } },
};

/** Everything was acted on or dismissed; the refresh is the way to ask again. */
export const NothingLeft: Story = {
  args: { items: [], suggestionSet: { ...SET, items: [] } },
};

/** A scan is running, which takes minutes. */
export const Scanning: Story = {
  args: { actions: { ...ACTIONS, isScanning: true } },
};
