import type { HomeExperiment } from "@posthog/core/home/homeSchemas";
import type { HomeFlagSuggestion } from "@posthog/ui/features/home/homeSuggestions";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { HomePage } from "./HomePage";
import { HomeSection } from "./HomeSection";

const DAY_MS = 86_400_000;

function suggestion(
  key: string,
  overrides: Partial<HomeFlagSuggestion["flag"]> = {},
  existingSpace: HomeFlagSuggestion["existingSpace"] = null,
): HomeFlagSuggestion {
  return {
    flag: {
      id: key.length,
      key,
      name: "Rebuilt checkout, behind a flag",
      active: true,
      rolloutPercentage: 25,
      hasExperiment: false,
      createdAt: Date.now() - DAY_MS,
      yours: true,
      createdBy: "Ada Lovelace",
      ...overrides,
    },
    spaceName: `feature-${key}`,
    existingSpace,
  };
}

function experiment(overrides: Partial<HomeExperiment> = {}): HomeExperiment {
  return {
    id: 1,
    name: "Checkout copy",
    description: "Shorter labels on the pay button",
    featureFlagKey: "new-checkout",
    stage: "running",
    startedAt: Date.now() - 6 * DAY_MS,
    endedAt: null,
    variants: ["control", "test"],
    yours: true,
    createdBy: "Ada Lovelace",
    ...overrides,
  };
}

/**
 * A stand-in for a stacked canvas. The real section renders a live sandboxed
 * iframe, which Storybook has no artifact origin to serve — the band it
 * occupies is what the story is here to show.
 */
function CanvasPlaceholder({ name }: { name: string }) {
  return (
    <HomeSection title={name}>
      <div className="flex h-[460px] items-center justify-center rounded-md border border-border bg-card text-muted-foreground text-sm">
        Canvas renders here
      </div>
    </HomeSection>
  );
}

const meta = {
  title: "Home/HomePage",
  component: HomePage,
  args: {
    isLoading: false,
    orgName: "Hedgehog Supply Co",
    suggestions: [
      suggestion("new-checkout"),
      suggestion("billing-v2", {
        id: 2,
        name: "Metered billing",
        active: false,
        rolloutPercentage: null,
        yours: false,
        createdBy: "Grace H",
      }),
      suggestion(
        "search-rerank",
        { id: 3, name: "Reranked search results", rolloutPercentage: 100 },
        { id: "chan-1", name: "feature-search-rerank" },
      ),
    ],
    experiments: [
      experiment(),
      experiment({
        id: 2,
        name: "Onboarding checklist",
        stage: "draft",
        startedAt: null,
        featureFlagKey: "onboarding-checklist",
        yours: false,
        createdBy: "Grace H",
      }),
    ],
    unavailable: [],
    canvasCount: 1,
    canvasSections: <CanvasPlaceholder name="Weekly numbers" />,
  },
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof HomePage>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

/** Nothing to pick up yet: the hero carries the whole message. */
export const Empty: Story = {
  args: {
    suggestions: [],
    experiments: [],
    canvasCount: 0,
    canvasSections: null,
  },
};

/** The login can't read one of the groups, so Home says so. */
export const GroupUnavailable: Story = {
  args: {
    experiments: [],
    unavailable: ["experiments"],
  },
};

export const Loading: Story = {
  args: { isLoading: true },
  // The skeletons are the story, so don't wait for them to go away.
  parameters: { testOptions: { waitForLoadersToDisappear: false } },
};
