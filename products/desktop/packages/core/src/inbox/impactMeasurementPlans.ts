import type {
  AnySignalReportArtefact,
  ImpactMeasurementPlanArtefact,
  ImpactMeasurementPlanContent,
} from "@posthog/shared/types";

/** Matches the web report detail, which shows at most this many plans. */
const MAX_VISIBLE_MEASUREMENT_PLANS = 6;

/**
 * The current version of each proposed measurement, newest first. Plans are
 * versioned by `metric_id`: a revision or an activation appends a new row, so
 * only the newest row per metric counts. A retired plan is withdrawn.
 */
export function selectImpactMeasurementPlans(
  artefacts: AnySignalReportArtefact[],
): ImpactMeasurementPlanArtefact[] {
  const plans = artefacts
    .filter(
      (artefact): artefact is ImpactMeasurementPlanArtefact =>
        artefact.type === "impact_measurement_plan" && !artefact.degraded,
    )
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  const newest = new Map<string, ImpactMeasurementPlanArtefact>();
  for (const plan of plans) {
    if (!newest.has(plan.content.metric_id)) {
      newest.set(plan.content.metric_id, plan);
    }
  }
  return [...newest.values()]
    .filter((plan) => !plan.content.retired)
    .slice(0, MAX_VISIBLE_MEASUREMENT_PLANS);
}

function withUnit(value: string, unit: string | null | undefined): string {
  return unit ? `${value} ${unit}` : value;
}

function formatCurrency(value: number, currency: string): string | null {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
    }).format(value);
  } catch {
    return null;
  }
}

export function formatImpactMeasurementValue(
  plan: Pick<ImpactMeasurementPlanContent, "value_format" | "unit">,
  value: number,
): string {
  const unit = plan.unit?.trim() || null;
  switch (plan.value_format ?? "number") {
    case "count":
      return withUnit(
        value.toLocaleString(undefined, { maximumFractionDigits: 0 }),
        unit,
      );
    case "percentage":
      return withUnit(
        `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}%`,
        unit === "%" ? null : unit,
      );
    case "percentage_scaled":
      return withUnit(
        `${(value * 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`,
        unit === "%" ? null : unit,
      );
    case "currency":
      return (
        (unit && formatCurrency(value, unit)) ??
        withUnit(value.toLocaleString(), unit)
      );
    default:
      return withUnit(value.toLocaleString(), unit);
  }
}

/** The proposed target, such as `at most 10 errors`. Null when the backend redacted it. */
export function impactMeasurementGoalLabel(
  plan: ImpactMeasurementPlanContent,
): string | null {
  if (plan.goal_value == null || !plan.goal_direction) {
    return null;
  }
  const direction = plan.goal_direction === "at_most" ? "at most" : "at least";
  return `${direction} ${formatImpactMeasurementValue(plan, plan.goal_value)}`;
}

/** When to judge the result, such as `7 days after release and 100 qualifying observations`. */
export function impactMeasurementDecisionRule(
  plan: ImpactMeasurementPlanContent,
): string | null {
  const parts: string[] = [];
  if (plan.decision_window_days) {
    parts.push(
      `${plan.decision_window_days} ${plan.decision_window_days === 1 ? "day" : "days"} after release`,
    );
  }
  if (plan.minimum_data_points) {
    parts.push(
      `${plan.minimum_data_points.toLocaleString()} qualifying ${plan.minimum_data_points === 1 ? "observation" : "observations"}`,
    );
  }
  return parts.length ? parts.join(" and ") : null;
}
