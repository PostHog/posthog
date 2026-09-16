import {
  formatModelRates,
  MODEL_COST_BASELINE_NAME,
  type ModelCostInfo,
} from "@posthog/core/billing/modelPricing";

/** The exact rates behind a multiplier, for the chip's title. */
export function modelCostTitle(cost: ModelCostInfo): string {
  return `Cost per token vs ${MODEL_COST_BASELINE_NAME} · ${formatModelRates(cost.price)}`;
}

/**
 * Per-token cost multiplier chip for priced model picker rows. Presentational
 * so the row's accessible name stays the model name; the title carries the
 * exact rates.
 */
export function ModelCostChip({ cost }: { cost: ModelCostInfo }) {
  return (
    <span
      className="ml-auto pl-3 font-normal text-[10px] text-muted-foreground/80 tabular-nums"
      title={modelCostTitle(cost)}
      aria-hidden="true"
    >
      {cost.multiplierLabel}
    </span>
  );
}

/** The legend for the chips: one muted line under a model list. */
export function ModelCostFooter() {
  return (
    <div className="px-2 pt-1 pb-1.5 text-[10px] text-muted-foreground/70">
      × is cost per token vs {MODEL_COST_BASELINE_NAME}
    </div>
  );
}
