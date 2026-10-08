import type { ServiceContainer } from "@posthog/di/container";
import { ServiceProvider } from "@posthog/di/react";
import {
  CLAUDE_SUBSCRIPTION_TOKEN_SETTINGS,
  type ClaudeSubscriptionTokenSettings,
} from "@posthog/ui/features/settings/claudeSubscriptionTokenSettings";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useMemo } from "react";
import { ClaudeCloudTokenSection } from "./ClaudeCloudTokenSection";

const meta: Meta<typeof ClaudeCloudTokenSection> = {
  title: "Settings/ClaudeCloudTokenSection",
  component: ClaudeCloudTokenSection,
  args: { cloudSubscriptionOn: false, onCreateToken: () => {} },
  decorators: [
    (Story, context) => {
      const { container, queryClient } = useMemo(() => {
        let saved = context.parameters.tokenSaved === true;
        const tokenSettings: ClaudeSubscriptionTokenSettings = {
          has: async () => {
            if (context.parameters.tokenError)
              throw new Error("Unlock your system key store and try again.");
            return saved;
          },
          save: async () => {
            saved = true;
          },
          clear: async () => {
            saved = false;
          },
        };
        const container: ServiceContainer = {
          get: () => tokenSettings,
          getAll: () => [],
          isBound: (token) => token === CLAUDE_SUBSCRIPTION_TOKEN_SETTINGS,
          bind: () => {
            throw new Error("Story services are fixed");
          },
        };
        return { container, queryClient: new QueryClient() };
      }, [context.parameters.tokenSaved, context.parameters.tokenError]);
      return (
        <ServiceProvider container={container}>
          <QueryClientProvider client={queryClient}>
            <div className="mx-auto my-8 max-w-2xl px-4">
              <Story />
            </div>
          </QueryClientProvider>
        </ServiceProvider>
      );
    },
  ],
};

export default meta;
type Story = StoryObj<typeof ClaudeCloudTokenSection>;

export const NoToken: Story = {};
export const StorageError: Story = { parameters: { tokenError: true } };
export const TokenSaved: Story = {
  args: { cloudSubscriptionOn: true },
  parameters: { tokenSaved: true },
};
