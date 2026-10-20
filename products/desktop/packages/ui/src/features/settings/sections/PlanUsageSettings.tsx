import {
  ArrowSquareOut,
  CaretDown,
  CaretUp,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  codeUsageMeter,
  codeUsageResetLabel,
  codeUsageWindowLabel,
  desktopUsageComponents,
  formatUsageQuantity,
  formatUsdAmount,
  isCodeUsageFreeTier,
} from "@posthog/core/billing/usageDisplay";
import type { UsageOutput } from "@posthog/core/usage/schemas";
import { BILLING_FLAG, CLOUD_COMPUTE_BILLING_FLAG } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { UsageMeter } from "@posthog/ui/features/billing/UsageMeter";
import {
  type SpendSnapshot,
  useSpendTotalsState,
} from "@posthog/ui/features/billing/useSpendTotals";
import { useUsage } from "@posthog/ui/features/billing/useUsage";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { SettingsSubsection } from "@posthog/ui/features/settings/components/SettingsSubsection";
import { PersonalSpendTotals } from "@posthog/ui/features/usage/components/PersonalSpendTotals";
import { SpendAnalysisSection } from "@posthog/ui/features/usage/components/SpendAnalysisSection";
import { useTrackUsageViewed } from "@posthog/ui/features/usage/useTrackUsageViewed";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { track } from "@posthog/ui/shell/analytics";
import { getBillingUrl } from "@posthog/ui/utils/urls";
import { Button, Callout, Flex, Text } from "@radix-ui/themes";
import { type ReactNode, useEffect, useState } from "react";

export function PlanUsageSettings() {
  const billingEnabled = useFeatureFlag(BILLING_FLAG);
  const cloudComputeEnabled = useFeatureFlag(CLOUD_COMPUTE_BILLING_FLAG);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const billingUrl = getBillingUrl(cloudRegion);

  const {
    usage,
    isLoading: usageLoading,
    refetch: refetchUsage,
  } = useUsage({ enabled: billingEnabled });
  const { totals: spendTotals, isLoading: spendTotalsLoading } =
    useSpendTotalsState();

  useEffect(() => {
    // refetchUsage is a refresh mutation, so it bypasses useUsage's `enabled`
    // gate — skip it for spend-only users.
    if (billingEnabled) void refetchUsage();
  }, [refetchUsage, billingEnabled]);

  const meter = codeUsageMeter(usage);
  useTrackUsageViewed({
    isLoading: billingEnabled && usageLoading,
    spendTotalsLoading,
    sustainedUsedPercent: usage?.sustained.used_percent ?? null,
    burstUsedPercent: usage?.burst.used_percent ?? null,
    meterKind: meter.kind,
    orgUsedUsd: meter.kind === "dollars" ? meter.usedUsd : null,
    orgLimitUsd: meter.kind === "dollars" ? meter.limitUsd : null,
    personalSpend30dUsd: spendTotals?.monthUsd ?? null,
  });

  return (
    <PlanUsageContent
      billingEnabled={billingEnabled}
      cloudComputeEnabled={cloudComputeEnabled}
      billingUrl={billingUrl}
      usage={usage}
      usageLoading={usageLoading}
      spendTotals={spendTotals}
      spendTotalsLoading={spendTotalsLoading}
      personalSpendAnalysis={<SpendAnalysisSection />}
    />
  );
}

interface PlanUsageContentProps {
  billingEnabled: boolean;
  cloudComputeEnabled: boolean;
  billingUrl: string | null | undefined;
  usage: UsageOutput | null | undefined;
  usageLoading: boolean;
  spendTotals: SpendSnapshot | null;
  spendTotalsLoading: boolean;
  personalSpendAnalysis?: ReactNode;
}

export function PlanUsageContent({
  billingEnabled,
  cloudComputeEnabled,
  billingUrl,
  usage,
  usageLoading,
  spendTotals,
  spendTotalsLoading,
  personalSpendAnalysis,
}: PlanUsageContentProps) {
  const freeTier = isCodeUsageFreeTier(usage);
  const orgLimitReached = usage?.ai_credits?.exhausted === true;
  const meter = codeUsageMeter(usage);
  const components = desktopUsageComponents(usage);
  const hasUsageMix =
    components?.tokenUsd != null && components.computeUsd != null;

  const openBilling = () => {
    if (billingUrl) window.open(billingUrl, "_blank", "noopener,noreferrer");
  };

  return (
    <Flex direction="column" gap="8">
      {billingEnabled && (
        <SettingsSubsection
          title="Organization usage"
          description="Combined token and cloud-compute spend counts toward your organization's shared allowance and limit"
          actions={
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
          }
        >
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

          {usageLoading ? (
            <LoadingState className="rounded-(--radius-3) border border-border bg-card p-4" />
          ) : meter.kind === "dollars" ? (
            <UsageMeter
              label={codeUsageWindowLabel(meter, freeTier)}
              percent={meter.percent}
              valueLabel={`${formatUsdAmount(meter.usedUsd)} of ${formatUsdAmount(meter.limitUsd)}${freeTier ? " included" : ""}`}
              detail={`${meter.exceeded ? "Limit exceeded. " : ""}${codeUsageResetLabel(meter)}`}
              breakdown={
                meter.breakdown
                  ? { ...meter.breakdown, usedUsd: meter.usedUsd }
                  : undefined
              }
              color={meter.exceeded ? "red" : undefined}
            />
          ) : meter.kind === "bucket" ? (
            <UsageMeter
              label={codeUsageWindowLabel(meter, freeTier)}
              percent={meter.bucket.used_percent}
              valueLabel={`${meter.bucket.used_percent.toFixed(2)}%`}
              detail={`${meter.bucket.exceeded ? "Limit exceeded. " : ""}${codeUsageResetLabel(meter)}`}
              color={meter.bucket.exceeded ? "red" : undefined}
            />
          ) : (
            <Flex
              align="center"
              justify="between"
              gap="4"
              p="4"
              className="rounded-(--radius-3) border border-border bg-card"
            >
              <Text color="gray" className="text-[13px]">
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
              {cloudComputeEnabled && hasUsageMix && (
                <UsageMix components={components} />
              )}
              <Text className="text-[12px] text-muted-foreground">
                {meter.kind === "dollars"
                  ? "This total comes from billing, so it can lag by 15 to 20 minutes. "
                  : ""}
                Your own spend below is near real time.
              </Text>
            </Flex>
          )}
        </SettingsSubsection>
      )}

      <PersonalSpendDisclosure
        totals={spendTotals}
        totalsLoading={spendTotalsLoading}
      >
        {personalSpendAnalysis}
      </PersonalSpendDisclosure>
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
      className="rounded-(--radius-3) border border-border bg-card"
    >
      <Text className="font-medium text-[13px] text-foreground">Usage mix</Text>
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
      <Text className="text-[12px] text-muted-foreground">
        Compute resources: {computeDetails}
      </Text>
    </Flex>
  );
}

function PersonalSpendDisclosure({
  totals,
  totalsLoading,
  children,
}: {
  totals: SpendSnapshot | null;
  totalsLoading: boolean;
  children: ReactNode;
}) {
  // The totals above read the window the guardrails already poll, so only the
  // charts and breakdowns wait for the disclosure.
  const [expanded, setExpanded] = useState(false);

  return (
    <SettingsSubsection
      title="Your spend"
      description="Near-real-time analysis of your activity, separate from organization billing"
      actions={
        <Button
          size="1"
          variant="outline"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? "Hide details" : "Show details"}
          {expanded ? <CaretUp size={12} /> : <CaretDown size={12} />}
        </Button>
      }
    >
      <PersonalSpendTotals totals={totals} isLoading={totalsLoading} />
      {expanded ? children : null}
    </SettingsSubsection>
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
      <Text className="text-[13px]">
        <strong>{percent}%</strong> {label}
        <span className="text-muted-foreground"> · {value}</span>
      </Text>
    </Flex>
  );
}
