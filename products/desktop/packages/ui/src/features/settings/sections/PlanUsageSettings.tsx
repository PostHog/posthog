import {
  ArrowSquareOut,
  CaretDown,
  CaretRight,
  CreditCard,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  codeUsageMeter,
  desktopUsageComponents,
  formatResetTime,
  formatUsageQuantity,
  formatUsdAmount,
  isCodeUsageFreeTier,
} from "@posthog/core/billing/usageDisplay";
import type { UsageOutput } from "@posthog/core/usage/schemas";
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
import { Button, Callout, Flex, Spinner, Text } from "@radix-ui/themes";
import { type ReactNode, useEffect, useState } from "react";

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

  return (
    <PlanUsageContent
      billingEnabled={billingEnabled}
      spendAnalysisEnabled={spendAnalysisEnabled}
      billingUrl={billingUrl}
      usage={usage}
      usageLoading={usageLoading}
      personalSpendAnalysis={<SpendAnalysisSection />}
    />
  );
}

interface PlanUsageContentProps {
  billingEnabled: boolean;
  spendAnalysisEnabled: boolean;
  billingUrl: string | null | undefined;
  usage: UsageOutput | null | undefined;
  usageLoading: boolean;
  personalSpendAnalysis?: ReactNode;
}

export function PlanUsageContent({
  billingEnabled,
  spendAnalysisEnabled,
  billingUrl,
  usage,
  usageLoading,
  personalSpendAnalysis,
}: PlanUsageContentProps) {
  const freeTier = isCodeUsageFreeTier(usage);
  const orgLimitReached = usage?.ai_credits?.exhausted === true;
  const meter = codeUsageMeter(usage);
  const components = desktopUsageComponents(usage);
  const hasUsageMix =
    components?.tokenUsd != null && components.computeUsd != null;

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
            gap="4"
            p="4"
            className="rounded-(--radius-3) border border-(--gray-5)"
          >
            <Flex align="start" justify="between" gap="4" wrap="wrap">
              <Flex direction="column" gap="1">
                <Text className="font-bold text-base">Organization usage</Text>
                <Text className="text-(--gray-11) text-sm">
                  Combined token and cloud-compute spend counts toward your
                  organization's shared allowance and limit.
                </Text>
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
              >
                {freeTier ? "Add payment method" : "Manage billing and limits"}
                <ArrowSquareOut size={12} />
              </Button>
            </Flex>
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
            {!usageLoading && (
              <Flex direction="column" gap="3">
                {hasUsageMix && <UsageMix components={components} />}
                <Text className="text-(--gray-9) text-[13px]">
                  Usage reporting may be delayed by 15–20 minutes.
                </Text>
              </Flex>
            )}
          </Flex>
        </>
      )}

      {spendAnalysisEnabled && (
        <PersonalSpendDisclosure>
          {personalSpendAnalysis}
        </PersonalSpendDisclosure>
      )}
    </Flex>
  );
}

function UsageMix({
  components,
}: {
  components: NonNullable<ReturnType<typeof desktopUsageComponents>>;
}) {
  const tokenUsd = components.tokenUsd ?? 0;
  const computeUsd = components.computeUsd ?? 0;
  const totalUsd = tokenUsd + computeUsd;
  const tokenPercent = totalUsd > 0 ? (tokenUsd / totalUsd) * 100 : 0;
  const roundedTokenPercent = Math.round(tokenPercent);
  const computeDetails = [
    components.cpuCoreSeconds == null
      ? "CPU unavailable"
      : formatUsageQuantity(components.cpuCoreSeconds, "core-seconds"),
    components.memoryGibSeconds == null
      ? "Memory unavailable"
      : formatUsageQuantity(components.memoryGibSeconds, "GiB-seconds"),
  ].join(" · ");

  return (
    <Flex
      direction="column"
      gap="3"
      p="4"
      className="rounded-(--radius-3) bg-(--gray-a2)"
    >
      <Text className="font-medium text-sm">Usage mix</Text>
      <div
        role="img"
        aria-label={`${roundedTokenPercent}% tokens and ${totalUsd > 0 ? 100 - roundedTokenPercent : 0}% cloud compute`}
        className="flex h-3 w-full overflow-hidden rounded-full bg-(--gray-a4)"
      >
        {totalUsd > 0 && (
          <>
            <div
              className="bg-(--purple-9)"
              style={{ width: `${tokenPercent}%` }}
            />
            <div className="flex-1 bg-(--blue-9)" />
          </>
        )}
      </div>
      <Flex align="center" gap="5" wrap="wrap">
        <MixLegend
          color="bg-(--purple-9)"
          label="Tokens"
          percent={roundedTokenPercent}
          value={formatUsdAmount(tokenUsd)}
        />
        <MixLegend
          color="bg-(--blue-9)"
          label="Cloud compute"
          percent={totalUsd > 0 ? 100 - roundedTokenPercent : 0}
          value={formatUsdAmount(computeUsd)}
        />
      </Flex>
      <Text className="text-(--gray-9) text-xs">
        Compute resources: {computeDetails}
      </Text>
    </Flex>
  );
}

function PersonalSpendDisclosure({ children }: { children: ReactNode }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <Flex
      direction="column"
      className="overflow-hidden rounded-(--radius-3) border border-(--gray-5)"
    >
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-4 p-4 text-left hover:bg-(--gray-a2) focus-visible:outline-(--accent-8) focus-visible:outline-2"
      >
        <Flex direction="column" gap="1">
          <Text className="font-medium text-sm">Your spend</Text>
          <Text className="text-(--gray-11) text-xs">
            Near-real-time analysis of your activity, separate from organization
            billing.
          </Text>
        </Flex>
        {expanded ? <CaretDown size={16} /> : <CaretRight size={16} />}
      </button>
      {expanded && children && (
        <div className="border-(--gray-5) border-t p-4">{children}</div>
      )}
    </Flex>
  );
}

function MixLegend({
  color,
  label,
  percent,
  value,
}: {
  color: string;
  label: string;
  percent: number;
  value: string;
}) {
  return (
    <Flex align="center" gap="2">
      <span className={`size-2 rounded-full ${color}`} />
      <Text className="text-sm">
        <strong>{percent}%</strong> {label}
        <span className="text-(--gray-9)"> · {value}</span>
      </Text>
    </Flex>
  );
}
