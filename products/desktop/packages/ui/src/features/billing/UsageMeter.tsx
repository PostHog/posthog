import { formatUsdAmount } from "@posthog/core/billing/usageDisplay";
import { cn } from "@posthog/quill";
import { Flex, Progress, Text } from "@radix-ui/themes";

interface UsageMeterBreakdown {
  includedUsd: number;
  spendLimitUsd: number;
  usedUsd: number;
}

interface UsageMeterProps {
  label: string;
  percent: number;
  valueLabel: string;
  detail: string;
  color?: "red";
  breakdown?: UsageMeterBreakdown;
}

const clampPercent = (value: number): number =>
  Math.min(100, Math.max(0, value));

export function UsageMeter({
  label,
  percent,
  valueLabel,
  detail,
  color,
  breakdown,
}: UsageMeterProps) {
  const borderColor = color === "red" ? "var(--red-7)" : "var(--gray-5)";

  return (
    <Flex
      direction="column"
      gap="3"
      p="4"
      style={{
        border: `1px solid ${borderColor}`,
      }}
      className="rounded-(--radius-3)"
    >
      <Flex align="center" justify="between">
        <Text className="font-medium text-sm">{label}</Text>
        <Text className="font-medium text-sm">{valueLabel}</Text>
      </Flex>
      {breakdown ? (
        <SegmentedUsageBar
          percent={percent}
          breakdown={breakdown}
          exceeded={color === "red"}
        />
      ) : (
        <Progress
          value={percent}
          size="2"
          color={color === "red" ? "red" : undefined}
        />
      )}
      <Text className="text-(--gray-9) text-[13px]">{detail}</Text>
    </Flex>
  );
}

function SegmentedUsageBar({
  percent,
  breakdown,
  exceeded,
}: {
  percent: number;
  breakdown: UsageMeterBreakdown;
  exceeded: boolean;
}) {
  const { includedUsd, spendLimitUsd, usedUsd } = breakdown;
  const totalUsd = includedUsd + spendLimitUsd;
  const hasPaidSegment = spendLimitUsd > 0 && totalUsd > 0;
  const includedFill =
    includedUsd > 0 ? clampPercent((usedUsd / includedUsd) * 100) : 100;
  const paidFill = hasPaidSegment
    ? clampPercent(((usedUsd - includedUsd) / spendLimitUsd) * 100)
    : 0;
  const includedDot = exceeded ? "bg-(--red-9)" : "bg-(--green-9)";
  const paidDot = exceeded ? "bg-(--red-9)" : "bg-(--accent-9)";

  return (
    <Flex direction="column" gap="2">
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(clampPercent(percent))}
        className="flex h-2 w-full gap-[3px]"
      >
        <div
          className="h-full overflow-hidden rounded-full bg-(--gray-a3)"
          style={{
            width: hasPaidSegment
              ? `${(includedUsd / totalUsd) * 100}%`
              : "100%",
          }}
        >
          <div
            className={cn(
              "h-full transition-[width] duration-300",
              includedDot,
            )}
            style={{ width: `${includedFill}%` }}
          />
        </div>
        {hasPaidSegment && (
          <div className="h-full flex-1 overflow-hidden rounded-full bg-(--gray-a3)">
            <div
              className={cn("h-full transition-[width] duration-300", paidDot)}
              style={{ width: `${paidFill}%` }}
            />
          </div>
        )}
      </div>
      <Flex align="center" gap="4" wrap="wrap">
        <Flex align="center" gap="2">
          <span className={cn("size-2 rounded-full", includedDot)} />
          <Text className="text-(--gray-9) text-[13px]">
            {formatUsdAmount(includedUsd)} included
          </Text>
        </Flex>
        {hasPaidSegment && (
          <Flex align="center" gap="2">
            <span className={cn("size-2 rounded-full", paidDot)} />
            <Text className="text-(--gray-9) text-[13px]">
              {formatUsdAmount(spendLimitUsd)} org spend limit
            </Text>
          </Flex>
        )}
      </Flex>
    </Flex>
  );
}
