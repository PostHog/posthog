import type { FeatureFlag, FlagType } from "./types.js";

/** Classify a flag as boolean release, multivariate, or remote config */
export function classifyFlagType(flag: FeatureFlag | undefined): FlagType {
  if (!flag) {
    return "boolean";
  }
  const filters = flag.filters as Record<string, unknown> | undefined;
  if (filters?.multivariate && typeof filters.multivariate === "object") {
    const mv = filters.multivariate as { variants?: unknown[] };
    if (mv.variants && mv.variants.length > 0) {
      return "multivariate";
    }
  }
  if (filters?.payloads && typeof filters.payloads === "object") {
    const payloads = filters.payloads as Record<string, unknown>;
    if (Object.values(payloads).some((v) => v !== null && v !== undefined)) {
      return "remote_config";
    }
  }
  return "boolean";
}

/** Check if a flag is fully rolled out (100%, no conditions, no multivariate) */
export function isFullyRolledOut(flag: FeatureFlag): boolean {
  const filters = flag.filters as Record<string, unknown> | undefined;
  if (!filters) {
    return false;
  }

  if (filters.multivariate && typeof filters.multivariate === "object") {
    const mv = filters.multivariate as { variants?: unknown[] };
    if (mv.variants && mv.variants.length > 0) {
      return false;
    }
  }

  if (filters.groups && Array.isArray(filters.groups)) {
    const groups = filters.groups as Array<Record<string, unknown>>;
    if (groups.length === 0) {
      return false;
    }
    return groups.every((g) => {
      const rollout = g.rollout_percentage;
      const props = g.properties;
      const hasConditions = Array.isArray(props) && props.length > 0;
      return rollout === 100 && !hasConditions;
    });
  }

  return false;
}

/** Extract rollout percentage from a flag's filters */
export function extractRollout(flag: FeatureFlag): number | null {
  const filters = flag.filters as Record<string, unknown> | undefined;
  if (filters?.groups && Array.isArray(filters.groups)) {
    for (const group of filters.groups) {
      if (typeof group === "object" && group !== null) {
        const rp = (group as Record<string, unknown>).rollout_percentage;
        if (typeof rp === "number") {
          return rp;
        }
      }
    }
  }
  return null;
}

/** Extract multivariate variants from a flag */
export function extractVariants(
  flag: FeatureFlag,
): { key: string; rollout_percentage: number }[] {
  const filters = flag.filters as Record<string, unknown> | undefined;
  if (filters?.multivariate && typeof filters.multivariate === "object") {
    const mv = filters.multivariate as {
      variants?: { key: string; rollout_percentage: number }[];
    };
    if (mv.variants && mv.variants.length > 0) {
      return mv.variants;
    }
  }
  return [];
}

/** Count release conditions (groups with property filters) */
export function extractConditionCount(flag: FeatureFlag): number {
  const filters = flag.filters as Record<string, unknown> | undefined;
  if (!filters?.groups || !Array.isArray(filters.groups)) {
    return 0;
  }
  return (filters.groups as Array<Record<string, unknown>>).filter(
    (g) =>
      g.properties &&
      Array.isArray(g.properties) &&
      (g.properties as unknown[]).length > 0,
  ).length;
}
