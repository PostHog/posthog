import type { ClaudeIntegrationStatus } from "@posthog/api-client/posthog-client";
import type { ServiceContainer } from "@posthog/di/container";
import { ServiceProvider } from "@posthog/di/react";
import { claudeCloudAccountQueryKey } from "@posthog/ui/features/settings/claudeCloudAccount";
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
  args: { cloudSubscriptionOn: false },
  decorators: [
    (Story, context) => {
      const serverStatus: ClaudeIntegrationStatus =
        context.parameters.serverStatus ?? "not_connected";
      const localToken = context.parameters.localToken === true;
      const expiresInDays: number = context.parameters.expiresInDays ?? 300;
      const { container, queryClient } = useMemo(() => {
        let saved = localToken;
        const tokenSettings: ClaudeSubscriptionTokenSettings = {
          has: async () => saved,
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
        const queryClient = new QueryClient();
        queryClient.setQueryData(claudeCloudAccountQueryKey(null), {
          status: serverStatus,
          connected_at: serverStatus === "connected" ? "2026-01-01" : null,
          expires_at:
            serverStatus === "connected"
              ? new Date(
                  Date.now() + expiresInDays * 24 * 60 * 60 * 1000 - 60_000,
                ).toISOString()
              : null,
        });
        return { container, queryClient };
      }, [serverStatus, localToken, expiresInDays]);
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
export const TokenSaved: Story = {
  args: { cloudSubscriptionOn: true },
  parameters: { serverStatus: "connected" },
};
export const TokenExpiresSoon: Story = {
  args: { cloudSubscriptionOn: true },
  parameters: { serverStatus: "connected", expiresInDays: 6 },
};
export const TokenExpiresToday: Story = {
  args: { cloudSubscriptionOn: true },
  parameters: { serverStatus: "connected", expiresInDays: 0 },
};
export const ReauthRequired: Story = {
  args: { cloudSubscriptionOn: true },
  parameters: { serverStatus: "reauth_required" },
};
export const LocalTokenOnly: Story = {
  args: { cloudSubscriptionOn: true },
  parameters: { localToken: true },
};
