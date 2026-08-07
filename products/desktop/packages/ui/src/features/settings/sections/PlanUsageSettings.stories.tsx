import type { UsageOutput } from "@posthog/core/usage/schemas";
import { PlanUsageContent } from "@posthog/ui/features/settings/sections/PlanUsageSettings";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { Flex, Text } from "@radix-ui/themes";

const usage = {
  product: "posthog_code",
  user_id: 1,
  sustained: {
    used_percent: 34,
    reset_at: "2026-09-01T00:00:00.000Z",
    exceeded: false,
  },
  burst: {
    used_percent: 4,
    reset_at: "2026-08-07T00:00:00.000Z",
    exceeded: false,
  },
  ai_credits: {
    exhausted: false,
    used_usd: 23.8,
    limit_usd: 70,
    breakdown: {
      token_credits: 1_840,
      compute_credits: 540,
      cpu_millicore_seconds: 12_450_000,
      memory_mib_seconds: 31_457_280,
    },
  },
  is_rate_limited: false,
  is_pro: true,
  code_usage_subscribed: true,
  billing_period_end: "2026-09-01T00:00:00.000Z",
} satisfies UsageOutput;

const PersonalSpendPreview = () => (
  <Flex
    direction="column"
    gap="3"
    pt="5"
    className="border-(--gray-5) border-t"
  >
    <Flex direction="column" gap="1">
      <Text className="font-bold text-base">Your spend</Text>
      <Text className="text-(--gray-11) text-sm">
        Near-real-time spend for your activity in the selected window. It may
        differ from the delayed organization billing period above.
      </Text>
    </Flex>
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {[
        ["Last 30 days", "$18.72"],
        ["Today", "$1.08"],
        ["Runs", "42"],
      ].map(([label, value]) => (
        <Flex
          key={label}
          direction="column"
          gap="1"
          p="3"
          className="rounded-(--radius-3) bg-(--gray-a2)"
        >
          <Text className="text-(--gray-11) text-xs">{label}</Text>
          <Text className="font-medium text-lg">{value}</Text>
        </Flex>
      ))}
    </div>
  </Flex>
);

const meta: Meta<typeof PlanUsageContent> = {
  title: "Billing/Plan and usage",
  component: PlanUsageContent,
  decorators: [
    (Story) => (
      <div className="mx-auto max-w-3xl p-6">
        <Story />
      </div>
    ),
  ],
  args: {
    billingEnabled: true,
    spendAnalysisEnabled: true,
    billingUrl: "https://app.posthog.com/organization/billing",
    usage,
    usageLoading: false,
    personalSpendAnalysis: <PersonalSpendPreview />,
  },
};

export default meta;
type Story = StoryObj<typeof PlanUsageContent>;

export const WithComponentBreakdown: Story = {};

export const BreakdownAwaitingData: Story = {
  args: {
    spendAnalysisEnabled: false,
    usage: { ...usage, ai_credits: { ...usage.ai_credits, breakdown: null } },
  },
};

export const ExplicitZeroUsage: Story = {
  args: {
    spendAnalysisEnabled: false,
    usage: {
      ...usage,
      ai_credits: {
        exhausted: false,
        used_usd: 0,
        limit_usd: 70,
        breakdown: {
          token_credits: 0,
          compute_credits: 0,
          cpu_millicore_seconds: 0,
          memory_mib_seconds: 0,
        },
      },
    },
  },
};

export const OrganizationLimitReached: Story = {
  args: {
    spendAnalysisEnabled: false,
    usage: {
      ...usage,
      ai_credits: { ...usage.ai_credits, exhausted: true, used_usd: 70 },
      is_rate_limited: true,
    },
  },
};

export const Loading: Story = {
  args: { usage: null, usageLoading: true, spendAnalysisEnabled: false },
};
