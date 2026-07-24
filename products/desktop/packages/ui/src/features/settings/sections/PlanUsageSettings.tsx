import {
  ArrowSquareOut,
  CreditCard,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  codeUsageMeter,
  formatResetTime,
  formatUsdAmount,
  isCodeUsageFreeTier,
} from "@posthog/core/billing/usageDisplay";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { BILLING_FLAG } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { UsageMeter } from "@posthog/ui/features/billing/UsageMeter";
import { useUsage } from "@posthog/ui/features/billing/useUsage";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { SpendAnalysisSection } from "@posthog/ui/features/usage/components/SpendAnalysisSection";
import { useSpendAnalysisEnabled } from "@posthog/ui/features/usage/useSpendAnalysisEnabled";
import { useTrackUsageViewed } from "@posthog/ui/features/usage/useTrackUsageViewed";
import { track } from "@posthog/ui/shell/analytics";
import { getBillingUrl } from "@posthog/ui/utils/urls";
import { Badge, Button, Callout, Flex, Spinner, Text } from "@radix-ui/themes";
import { useEffect } from "react";

export function PlanUsageSettings() {
  const billingEnabled = useFeatureFlag(BILLING_FLAG);
  const spendAnalysisEnabled = useSpendAnalysisEnabled();
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const billingUrl = getBillingUrl(cloudRegion);

  const {
    usage,
    isLoading: usageLoading,
    refetch: refetchUsage,
  } = useUsage({ enabled: billingEnabled });

  useEffect(() => {
    // refetchUsage is a refresh mutation, so it bypasses useUsage's `enabled`
    // gate — skip it for spend-only users.
    if (billingEnabled) void refetchUsage();
  }, [refetchUsage, billingEnabled]);

  useTrackUsageViewed({
    isLoading: billingEnabled && usageLoading,
    isPro: usage?.is_pro ?? false,
    sustainedUsedPercent: usage?.sustained.used_percent ?? null,
    burstUsedPercent: usage?.burst.used_percent ?? null,
  });

  // Tri-state: unknown (absent field) must render as subscribed, never free.
  const freeTier = isCodeUsageFreeTier(usage);
  const subscribed = usage?.code_usage_subscribed === true;
  const orgLimitReached = usage?.ai_credits?.exhausted === true;
  const meter = codeUsageMeter(usage);

  const openBilling = () => {
    if (billingUrl) window.open(billingUrl, "_blank");
  };

  if (!billingEnabled && !spendAnalysisEnabled) {
    return (
      <Empty className="mx-auto max-w-md py-16">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <CreditCard size={24} />
          </EmptyMedia>
          <EmptyTitle>Plan & usage isn't available</EmptyTitle>
          <EmptyDescription>
            Billing and usage reporting aren't enabled for your account yet.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <Flex direction="column" gap="5">
      {billingEnabled && (
        <>
          {orgLimitReached && (
            <Callout.Root color="red" size="1">
              <Callout.Icon>
                <WarningCircle size={16} />
              </Callout.Icon>
              <Callout.Text>
                <Flex direction="column" gap="2">
                  <Text className="text-sm">
                    Your organization has reached its usage limit for this
                    billing period.
                  </Text>
                  <Button
                    size="1"
                    variant="outline"
                    color="red"
                    disabled={!billingUrl}
                    onClick={openBilling}
                    className="self-start"
                  >
                    Manage billing
                    <ArrowSquareOut size={12} />
                  </Button>
                </Flex>
              </Callout.Text>
            </Callout.Root>
          )}

          <Flex
            direction="column"
            gap="3"
            p="4"
            className="rounded-(--radius-3) border border-(--gray-5)"
          >
            <Flex align="center" justify="between">
              <Flex direction="column" gap="1">
                <Text className="font-bold text-base">
                  {freeTier ? "Free tier" : "Usage-based billing"}
                </Text>
                <Text className="text-(--gray-11) text-sm">
                  {freeTier
                    ? "Your organization's first $20 of usage each month is included, with access to open models. Add a payment method to unlock premium models — you only pay for what you use."
                    : "Your organization pays for usage at cost — no seats, no subscriptions. The first $20 each month is included."}
                </Text>
              </Flex>
              {subscribed && (
                <Badge variant="soft" color="green" radius="full">
                  Active
                </Badge>
              )}
            </Flex>
            <Button
              size="1"
              variant={freeTier ? "solid" : "outline"}
              disabled={!billingUrl}
              onClick={() => {
                if (freeTier) {
                  track(ANALYTICS_EVENTS.UPGRADE_PROMPT_CLICKED, {
                    surface: "plan_page_card",
                  });
                }
                openBilling();
              }}
              className="self-start"
            >
              {freeTier
                ? "Add payment method"
                : "Manage billing and spend limits"}
              <ArrowSquareOut size={12} />
            </Button>
          </Flex>

          <Flex direction="column" gap="3">
            <Text className="font-medium text-(--gray-9) text-sm">
              Organization usage
            </Text>
            {usageLoading ? (
              <Flex
                align="center"
                justify="center"
                p="4"
                className="rounded-(--radius-3) border border-(--gray-5)"
              >
                <Spinner size="2" />
              </Flex>
            ) : meter.kind === "dollars" ? (
              <UsageMeter
                label={freeTier ? "Monthly free usage" : "Usage this period"}
                percent={meter.percent}
                valueLabel={`${formatUsdAmount(meter.usedUsd)} of ${formatUsdAmount(meter.limitUsd)}${freeTier ? " included" : ""}`}
                detail={`${meter.exceeded ? "Limit exceeded. " : ""}${formatResetTime(meter.resetAt, { label: "Billing period ends" })}`}
                breakdown={
                  meter.breakdown
                    ? { ...meter.breakdown, usedUsd: meter.usedUsd }
                    : undefined
                }
                color={meter.exceeded ? "red" : undefined}
              />
            ) : meter.kind === "bucket" ? (
              <UsageMeter
                label="Monthly free usage"
                percent={meter.bucket.used_percent}
                valueLabel={`${meter.bucket.used_percent.toFixed(2)}%`}
                detail={`${meter.bucket.exceeded ? "Limit exceeded. " : ""}${formatResetTime(meter.bucket.reset_at)}`}
                color={meter.bucket.exceeded ? "red" : undefined}
              />
            ) : (
              <Flex
                align="center"
                justify="between"
                p="4"
                className="rounded-(--radius-3) border border-(--gray-5)"
              >
                <Text color="gray" className="text-sm">
                  {usage
                    ? "Usage is billed to your organization. View detailed usage and spend in PostHog."
                    : "Unable to load usage data"}
                </Text>
                {usage && (
                  <Button
                    size="1"
                    variant="outline"
                    disabled={!billingUrl}
                    onClick={openBilling}
                  >
                    View usage
                    <ArrowSquareOut size={12} />
                  </Button>
                )}
              </Flex>
            )}
          </Flex>
        </>
      )}

      {spendAnalysisEnabled && <SpendAnalysisSection />}
    </Flex>
  );
}
