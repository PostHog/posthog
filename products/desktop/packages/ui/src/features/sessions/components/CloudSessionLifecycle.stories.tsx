import {
  CloudStreamDisconnectedBanner,
  SandboxUnavailableBanner,
} from "@posthog/ui/features/sessions/components/CloudSessionLifecycle";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof SandboxUnavailableBanner> = {
  title: "Sessions/CloudSessionLifecycle",
  component: SandboxUnavailableBanner,
  parameters: {
    layout: "padded",
  },
};

export default meta;
type Story = StoryObj<typeof SandboxUnavailableBanner>;

/** Amber "waiting to reconnect" state — the run has not failed. */
export const SandboxUnavailable: Story = {
  args: {
    onRetry: () => undefined,
  },
};

/** Red "stream failed" state, for side-by-side comparison of tone. */
export const StreamDisconnected: StoryObj<typeof CloudStreamDisconnectedBanner> =
  {
    render: () => (
      <CloudStreamDisconnectedBanner
        errorTitle="Lost connection"
        errorMessage="The cloud run stream ended. Retry to reconnect."
        onRetry={() => undefined}
      />
    ),
  };
