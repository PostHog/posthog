import { SessionFooter } from "@posthog/ui/features/sessions/components/SessionFooter";
import type { ContextUsage } from "@posthog/ui/features/sessions/hooks/useContextUsage";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof SessionFooter> = {
  title: "Sessions/SessionFooter",
  component: SessionFooter,
  parameters: {
    layout: "padded",
  },
};

export default meta;
type Story = StoryObj<typeof SessionFooter>;

const usage: ContextUsage = {
  used: 788_000,
  size: 1_000_000,
  percentage: 79,
  cost: null,
  breakdown: null,
};

const generatingArgs = {
  isPromptPending: true,
  promptStartedAt: Date.now() - 5_400,
  lastGenerationDuration: null,
  usage,
};

/** Wraps the footer in fixed-width boxes so narrow panes are easy to eyeball. */
function AtWidths({ args }: { args: Parameters<typeof SessionFooter>[0] }) {
  return (
    <div className="flex flex-col gap-4">
      {[720, 480, 400, 340, 280, 220].map((width) => (
        <div key={width}>
          <div className="mb-1 text-[11px] text-gray-9">{width}px</div>
          <div
            className="rounded border border-gray-6 border-dashed px-2"
            style={{ width }}
          >
            <SessionFooter {...args} />
          </div>
        </div>
      ))}
    </div>
  );
}

export const GeneratingAtNarrowWidths: Story = {
  args: generatingArgs,
  render: (args) => <AtWidths args={args} />,
};

export const GeneratingWithQueueAtNarrowWidths: Story = {
  args: { ...generatingArgs, queuedCount: 2 },
  render: (args) => <AtWidths args={args} />,
};

export const AwaitingPermissionAtNarrowWidths: Story = {
  args: { ...generatingArgs, hasPendingPermission: true },
  render: (args) => <AtWidths args={args} />,
};

export const IdleAtNarrowWidths: Story = {
  args: {
    isPromptPending: false,
    lastGenerationDuration: 331_000,
    usage,
  },
  render: (args) => <AtWidths args={args} />,
};
