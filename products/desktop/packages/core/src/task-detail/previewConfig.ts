import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { flattenConfigValues } from "@posthog/core/task-detail/configOptions";
import type { Adapter } from "@posthog/shared";

export interface PreviewSettingsSnapshot {
  defaultInitialTaskMode: string;
  lastUsedInitialTaskMode: string | null | undefined;
  defaultReasoningEffort: string;
  lastUsedReasoningEffort: string | null | undefined;
}

export interface EffortOption {
  value: string;
}

const EFFORT_RANK: Record<string, number> = {
  low: 0,
  medium: 1,
  high: 2,
  xhigh: 3,
  max: 4,
};

export function clampEffortToAvailable(
  desired: string,
  available: string[],
): string | null {
  if (available.length === 0) return null;
  if (available.includes(desired)) return desired;

  const desiredRank = EFFORT_RANK[desired];
  if (desiredRank === undefined) {
    return available[available.length - 1];
  }

  const ranked = available
    .map((value) => ({ value, rank: EFFORT_RANK[value] }))
    .filter((entry): entry is { value: string; rank: number } =>
      Number.isFinite(entry.rank),
    );
  if (ranked.length === 0) return available[0];

  return ranked.reduce((closest, entry) =>
    Math.abs(entry.rank - desiredRank) < Math.abs(closest.rank - desiredRank)
      ? entry
      : closest,
  ).value;
}

export function deriveInitialConfig(
  options: SessionConfigOption[],
  settings: PreviewSettingsSnapshot,
  adapter: Adapter,
): SessionConfigOption[] {
  const {
    defaultInitialTaskMode,
    lastUsedInitialTaskMode,
    defaultReasoningEffort,
    lastUsedReasoningEffort,
  } = settings;

  const modeOpt = options.find((o) => o.id === "mode");
  const serverDefault = modeOpt?.currentValue;
  const availableValues: string[] = modeOpt ? flattenConfigValues(modeOpt) : [];

  let initialMode: string;
  if (
    defaultInitialTaskMode === "last_used" &&
    lastUsedInitialTaskMode &&
    availableValues.includes(lastUsedInitialTaskMode)
  ) {
    initialMode = lastUsedInitialTaskMode;
  } else {
    const fallbackDefault = adapter === "codex" ? "auto" : "plan";
    initialMode =
      typeof serverDefault === "string" &&
      availableValues.includes(serverDefault)
        ? serverDefault
        : fallbackDefault;
  }

  const withMode = options.map((opt) =>
    opt.id === "mode"
      ? ({ ...opt, currentValue: initialMode } as SessionConfigOption)
      : opt,
  );

  return withMode.map((opt) => {
    if (opt.category !== "thought_level" || opt.type !== "select") {
      return opt;
    }
    const validValues = flattenConfigValues(opt);
    if (defaultReasoningEffort === "last_used") {
      if (
        lastUsedReasoningEffort &&
        validValues.includes(lastUsedReasoningEffort)
      ) {
        return {
          ...opt,
          currentValue: lastUsedReasoningEffort,
        } as SessionConfigOption;
      }
      return opt;
    }
    const clamped = clampEffortToAvailable(defaultReasoningEffort, validValues);
    if (clamped) {
      return { ...opt, currentValue: clamped } as SessionConfigOption;
    }
    return opt;
  });
}

export interface ApplyConfigChangeArgs {
  adapter: Adapter;
  configId: string;
  value: string;
  effortOptions: EffortOption[] | undefined;
  settings: PreviewSettingsSnapshot;
}

export function applyConfigChange(
  options: SessionConfigOption[],
  args: ApplyConfigChangeArgs,
): SessionConfigOption[] {
  const { adapter, configId, value, effortOptions, settings } = args;

  let updated = options.map((opt) =>
    opt.id === configId
      ? ({ ...opt, currentValue: value } as SessionConfigOption)
      : opt,
  );

  if (configId !== "model") {
    return updated;
  }

  const existingIdx = updated.findIndex((o) => o.category === "thought_level");
  const effortOptionId =
    existingIdx >= 0
      ? updated[existingIdx].id
      : adapter === "codex"
        ? "reasoning_effort"
        : "effort";

  const { lastUsedReasoningEffort, defaultReasoningEffort } = settings;
  const isValidEffort = (effort: unknown): effort is string =>
    typeof effort === "string" &&
    !!effortOptions?.some((e) => e.value === effort);
  const resolveEffortFallback = (): string => {
    if (
      defaultReasoningEffort !== "last_used" &&
      isValidEffort(defaultReasoningEffort)
    ) {
      return defaultReasoningEffort;
    }
    return isValidEffort(lastUsedReasoningEffort)
      ? lastUsedReasoningEffort
      : "high";
  };

  if (effortOptions && existingIdx >= 0) {
    const currentEffort = updated[existingIdx].currentValue;
    const nextEffort = isValidEffort(currentEffort)
      ? currentEffort
      : resolveEffortFallback();
    updated[existingIdx] = {
      ...updated[existingIdx],
      currentValue: nextEffort,
      options: effortOptions,
    } as SessionConfigOption;
  } else if (effortOptions && existingIdx === -1) {
    const nextEffort = resolveEffortFallback();
    updated = [
      ...updated,
      {
        id: effortOptionId,
        name: adapter === "codex" ? "Reasoning Level" : "Effort",
        type: "select",
        currentValue: nextEffort,
        options: effortOptions,
        category: "thought_level",
        description:
          adapter === "codex"
            ? "Controls how much reasoning effort the model uses"
            : "Controls how much effort Claude puts into its response",
      } as SessionConfigOption,
    ];
  } else if (!effortOptions && existingIdx >= 0) {
    updated = updated.filter((o) => o.category !== "thought_level");
  }

  return updated;
}
