import type { TaskUsage } from "@posthog/api-client/posthog-client";
import type { ServiceContainer } from "@posthog/di/container";
import { ServiceProvider } from "@posthog/di/react";
import { TASK_COST_VISIBLE_FLAG } from "@posthog/shared";
import {
  FEATURE_FLAGS,
  type FeatureFlags,
} from "@posthog/ui/features/feature-flags/identifiers";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useMemo } from "react";
import { ContextUsageIndicator } from "./ContextUsageIndicator";

const meta: Meta<typeof ContextUsageIndicator> = {
  title: "Sessions/ContextUsageIndicator",
  component: ContextUsageIndicator,
  args: {
    taskId: "loop-task-example",
    originProduct: "loop",
    focused: false,
    usage: { used: 50_000, size: 200_000, percentage: 25, breakdown: null },
  },
  parameters: { costVisible: true, layout: "padded" },
  decorators: [
    (Story, context) => {
      const { container, queryClient } = useMemo(() => {
        const flags: FeatureFlags = {
          isEnabled: (key) =>
            key === TASK_COST_VISIBLE_FLAG && context.parameters.costVisible,
          getPayload: () => undefined,
          getVariant: () => undefined,
          onFlagsLoaded: () => () => {},
        };
        const container: ServiceContainer = {
          get: () => flags,
          getAll: () => [],
          isBound: (token) => token === FEATURE_FLAGS,
          bind: () => {
            throw new Error("Story services are fixed");
          },
        };
        const queryClient = new QueryClient();
        queryClient.setQueryData<TaskUsage>(
          ["task-usage", "loop-task-example"],
          { token_cost_usd: 0.4, compute_cost_usd: 0.02, total_cost_usd: 0.42 },
        );
        return { container, queryClient };
      }, [context.parameters.costVisible]);
      return (
        <ServiceProvider container={container}>
          <QueryClientProvider client={queryClient}>
            <div className="flex justify-end">
              <Story />
            </div>
          </QueryClientProvider>
        </ServiceProvider>
      );
    },
  ],
};

export default meta;
type Story = StoryObj<typeof ContextUsageIndicator>;

export const Loop: Story = {};
export const WorkflowLoop: Story = { args: { originProduct: "workflow" } };
export const WithoutContext: Story = { args: { usage: null } };
export const CostFlagOff: Story = { parameters: { costVisible: false } };
