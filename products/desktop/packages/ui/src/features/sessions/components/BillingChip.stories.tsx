import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { BillingChip } from "./BillingChip";

const meta: Meta<typeof BillingChip> = {
  title: "Sessions/BillingChip",
  component: BillingChip,
};

export default meta;

type Story = StoryObj<typeof BillingChip>;

function Harness({
  storedAccess,
  workspaceMode,
  cloudSubscriptionOn = false,
}: {
  storedAccess: "own-subscription" | "posthog-gateway";
  workspaceMode: "local" | "cloud";
  cloudSubscriptionOn?: boolean;
}) {
  useSettingsStore.getState().setClaudeModelAccess(storedAccess);
  useSettingsStore.getState().setClaudeCloudSubscriptionOn(cloudSubscriptionOn);
  return (
    <div className="flex h-40 items-end p-2">
      <BillingChip adapter="claude" workspaceMode={workspaceMode} />
    </div>
  );
}

export const PostHogBilling: Story = {
  render: () => (
    <Harness storedAccess="posthog-gateway" workspaceMode="local" />
  ),
};

/**
 * The stored pick is the Anthropic plan, but Storybook never resolves the
 * subscription status query, so the provider counts as logged out. The chip
 * reads the access the run would use, not the pick.
 */
export const ProviderPickWithoutLogin: Story = {
  render: () => (
    <Harness storedAccess="own-subscription" workspaceMode="local" />
  ),
};

export const CloudTask: Story = {
  render: () => (
    <Harness storedAccess="own-subscription" workspaceMode="cloud" />
  ),
};

/**
 * The cloud pick is stored, but the cloud plan billing is not offered here, so
 * a run would be refused. The chip says so instead of naming the plan.
 */
export const CloudPickUnavailable: Story = {
  render: () => (
    <Harness
      storedAccess="own-subscription"
      workspaceMode="cloud"
      cloudSubscriptionOn
    />
  ),
};
