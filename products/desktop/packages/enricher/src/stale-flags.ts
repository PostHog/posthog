import { isFullyRolledOut } from "./flag-classification.js";
import type {
  Experiment,
  FeatureFlag,
  StalenessCheckOptions,
  StalenessReason,
} from "./types.js";

/** Classify why a flag key is stale, or return null if it's not stale. */
export function classifyStaleness(
  flagKey: string,
  flag: FeatureFlag | undefined,
  experiments: Experiment[],
  options: StalenessCheckOptions = {},
): StalenessReason | null {
  if (!flag) {
    return "not_in_posthog";
  }

  if (!flag.active) {
    return "inactive";
  }

  const experiment = experiments.find((e) => e.feature_flag_key === flagKey);
  if (experiment?.end_date) {
    return "experiment_complete";
  }

  if (isFullyRolledOut(flag)) {
    const ageDays = options.staleFlagAgeDays ?? 30;
    if (ageDays > 0 && flag.created_at) {
      const createdAt = new Date(flag.created_at);
      const ageMs = Date.now() - createdAt.getTime();
      if (ageMs < ageDays * 86_400_000) {
        return null;
      }
    }
    return "fully_rolled_out";
  }

  return null;
}

/** Sort order for staleness reasons (most severe first) */
export const STALENESS_ORDER: Record<StalenessReason, number> = {
  not_in_posthog: 0,
  inactive: 1,
  experiment_complete: 2,
  fully_rolled_out: 3,
};
