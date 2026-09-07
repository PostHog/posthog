import {
  formatModelRates,
  MODEL_COST_BASELINE_NAME,
  modelCostInfo,
} from "@posthog/core/billing/modelPricing";

/** The exact rates behind a multiplier, for the chip's title. */
export function modelCostTitle(modelId: string): string | undefined {
  const cost = modelCostInfo(modelId);
  if (!cost) return undefined;
  return `Cost per token vs ${MODEL_COST_BASELINE_NAME} · ${formatModelRates(cost.price)}`;
}

/**
 * Per-token cost multiplier chip for model picker rows. Renders nothing for
 * unpriced models so a chip is never wrong. Presentational so the row's
 * accessible name stays the model name; the title carries the exact rates.
 */
export function ModelCostChip({ modelId }: { modelId: string }) {
  const cost = modelCostInfo(modelId);
  if (!cost) return null;
  return (
    <span
      className="ml-auto pl-3 font-normal text-[10px] text-muted-foreground/80 tabular-nums"
      title={modelCostTitle(modelId)}
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
