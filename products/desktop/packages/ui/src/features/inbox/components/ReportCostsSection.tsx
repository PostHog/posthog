import { CoinsIcon } from "@phosphor-icons/react";
import type { TaskUsage } from "@posthog/api-client/posthog-client";
import { cn } from "@posthog/quill";
import { TASK_COST_FLAG, TASK_COST_VISIBLE_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { formatCostUsd } from "@posthog/ui/features/sessions/contextColors";

// Reports have no backend cost rollup yet, so the section shows placeholder
// figures, shaped like `TaskUsage` so real data is a drop-in swap.
const PLACEHOLDER_USAGE: TaskUsage = {
  token_cost_usd: 42.53,
  compute_cost_usd: 7.44,
  total_cost_usd: 49.97,
};

/**
 * Cost of the agent work behind a report, following the session composer's
 * estimated-cost breakdown: the total, split into tokens and cloud compute.
 * Gated like the session cost: the task-cost flag reveals the section, and
 * the visible flag additionally puts the total on the collapsed header.
 */
export function ReportCostsSection() {
  const costEnabled = useFeatureFlag(TASK_COST_FLAG) || import.meta.env.DEV;
  const costVisible = useFeatureFlag(TASK_COST_VISIBLE_FLAG);

  if (!costEnabled) return null;

  return (
    <ReportCostsSectionView
      usage={PLACEHOLDER_USAGE}
      showHeaderTotal={costVisible}
    />
  );
}

export function ReportCostsSectionView({
  usage,
  showHeaderTotal = false,
  defaultCollapsed = true,
}: {
  usage: TaskUsage;
  showHeaderTotal?: boolean;
  defaultCollapsed?: boolean;
}) {
  return (
    <DetailSection
      Icon={CoinsIcon}
      title="Costs"
      collapsible
      defaultCollapsed={defaultCollapsed}
      rightSlot={
        showHeaderTotal ? (
          <span className="text-[12px] text-gray-10 tabular-nums">
            {formatCostUsd(usage.total_cost_usd)}
          </span>
        ) : undefined
      }
    >
      <div className="overflow-hidden rounded-(--radius-1) border border-(--gray-4)">
        <div className="flex items-center justify-between gap-6 bg-(--gray-2) px-2.5 py-1.5">
          <span className="font-medium text-[11px] text-gray-10">
            Estimated cost
          </span>
          <span className="font-semibold text-[15px] text-gray-12 tabular-nums leading-none">
            {formatCostUsd(usage.total_cost_usd)}
          </span>
        </div>
        <div className="grid grid-cols-2 border-(--gray-4) border-t">
          <CostDetail label="Tokens" value={usage.token_cost_usd} />
          <CostDetail
            label="Cloud compute"
            value={usage.compute_cost_usd}
            divided
          />
        </div>
      </div>
    </DetailSection>
  );
}

function CostDetail({
  label,
  value,
  divided = false,
}: {
  label: string;
  value: number;
  divided?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex min-w-0 flex-col px-2.5 py-1.5",
        divided && "border-(--gray-4) border-l",
      )}
    >
      <span className="truncate text-[10px] text-gray-10">{label}</span>
      <span className="font-medium text-[12px] text-gray-12 tabular-nums">
        {formatCostUsd(value)}
      </span>
    </div>
  );
}
