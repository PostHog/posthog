import type { Meta, StoryObj } from "@storybook/react-vite";
import {
  ResponderAgentRoster,
  type ResponderSourceState,
} from "./ResponderAgentRoster";
import type { ResponderAgentSource } from "./responderAgentMeta";

const SCANNERS = [
  {
    id: "s1",
    name: "Checkout friction",
    detail: "Flags hesitation and retries on the payment step.",
    kind: "monitor",
    enabled: true,
  },
  {
    id: "s2",
    name: "Onboarding drop-off",
    detail: "Scores how far a new account gets in its first session.",
    kind: "scorer",
    enabled: false,
  },
  {
    id: "s3",
    name: "Search dead ends",
    kind: "classifier",
    enabled: false,
  },
];

const SIGNAL_TYPES = [
  {
    id: "issue_created",
    name: "New issue",
    detail: "An error that has not been seen before.",
    enabled: true,
  },
  {
    id: "issue_reopened",
    name: "Reopened issue",
    detail: "A resolved issue that came back.",
    enabled: true,
  },
  {
    id: "issue_spiking",
    name: "Spiking issue",
    detail: "A known issue whose rate jumped above its baseline.",
    enabled: false,
  },
];

const SOURCE_STATES: Partial<
  Record<ResponderAgentSource, ResponderSourceState>
> = {
  error_tracking: {
    requiresSetup: false,
    loading: false,
    entities: SIGNAL_TYPES,
  },
  replay_vision: { requiresSetup: false, loading: false, entities: SCANNERS },
  conversations: { requiresSetup: false, loading: false },
  health_checks: { requiresSetup: false, loading: false },
  llm_analytics: { requiresSetup: false, loading: false },
  github: { requiresSetup: false, loading: false, syncStatus: "completed" },
  linear: { requiresSetup: true, loading: false },
  zendesk: { requiresSetup: true, loading: false },
  pganalyze: { requiresSetup: true, loading: false },
};

const meta = {
  title: "Inbox/ResponderAgentRoster",
  component: ResponderAgentRoster,
  decorators: [
    (Story) => (
      <div className="max-w-[900px] p-4">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof ResponderAgentRoster>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    value: { error_tracking: true, replay_vision: true, github: true },
    sourceStates: SOURCE_STATES,
  },
};

export const NoScannersYet: Story = {
  args: {
    value: { error_tracking: true },
    sourceStates: {
      ...SOURCE_STATES,
      replay_vision: { requiresSetup: false, loading: false, entities: [] },
    },
  },
};

export const ScannersLoading: Story = {
  args: {
    value: {},
    sourceStates: {
      ...SOURCE_STATES,
      replay_vision: {
        requiresSetup: false,
        loading: false,
        entities: [],
        entitiesLoading: true,
      },
    },
  },
};
