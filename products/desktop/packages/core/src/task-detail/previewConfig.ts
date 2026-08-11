import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { flattenConfigValues } from "@posthog/core/task-detail/configOptions";
import type { Adapter } from "@posthog/shared";
import { EFFORT_LEVELS } from "@posthog/shared/domain-types";

export const CONTEXT_WINDOW_OPTION_CATEGORY = "_context_window";
export const FAST_MODE_OPTION_CATEGORY = "_fast_mode";

export interface PreviewSettingsSnapshot {
  defaultInitialTaskMode: string;
  lastUsedInitialTaskMode: string | null | undefined;
  defaultReasoningEffort: string;
  lastUsedReasoningEffort: string | null | undefined;
  lastUsedContextWindow?: "200k" | "1m" | null;
  lastUsedFastMode?: boolean | null;
}

export interface EffortOption {
  value: string;
}

const EFFORT_RANK: Record<string, number> = Object.fromEntries(
  EFFORT_LEVELS.map((level, rank) => [level, rank]),
);

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
    if (opt.type === "select" && opt.id === "context_window") {
      const desired = settings.lastUsedContextWindow;
      if (desired && flattenConfigValues(opt).includes(desired)) {
        return { ...opt, currentValue: desired } as SessionConfigOption;
      }
      return opt;
    }
    if (opt.type === "select" && opt.id === "fast") {
      const desired =
        settings.lastUsedFastMode == null
          ? undefined
          : settings.lastUsedFastMode
            ? "on"
            : "off";
      if (desired && flattenConfigValues(opt).includes(desired)) {
        return { ...opt, currentValue: desired } as SessionConfigOption;
      }
      return opt;
    }
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
  contextWindowOptions?: EffortOption[];
  fastModeOptions?: EffortOption[];
  settings: PreviewSettingsSnapshot;
}

interface ToggleOptionSpec {
  id: string;
  name: string;
  category: string;
  description: string;
  options: EffortOption[] | undefined;
  defaultValue: string;
}

function syncToggleOption(
  options: SessionConfigOption[],
  spec: ToggleOptionSpec,
): SessionConfigOption[] {
  const idx = options.findIndex((o) => o.id === spec.id);
  if (!spec.options) {
    return idx >= 0 ? options.filter((o) => o.id !== spec.id) : options;
  }
  if (idx >= 0) {
    const current = options[idx];
    const currentValue =
      current.type === "select" &&
      spec.options.some((o) => o.value === current.currentValue)
        ? current.currentValue
        : spec.defaultValue;
    return options.map((o, i) =>
      i === idx
        ? ({ ...o, currentValue, options: spec.options } as SessionConfigOption)
        : o,
    );
  }
  return [
    ...options,
    {
      id: spec.id,
      name: spec.name,
      type: "select",
      currentValue: spec.defaultValue,
      options: spec.options,
      category: spec.category,
      description: spec.description,
    } as SessionConfigOption,
  ];
}

export function applyConfigChange(
  options: SessionConfigOption[],
  args: ApplyConfigChangeArgs,
): SessionConfigOption[] {
  const {
    adapter,
    configId,
    value,
    effortOptions,
    contextWindowOptions,
    fastModeOptions,
    settings,
  } = args;

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

  updated = syncToggleOption(updated, {
    id: "context_window",
    name: "Context Window",
    category: CONTEXT_WINDOW_OPTION_CATEGORY,
    description: "Choose the context window size for this session",
    options: contextWindowOptions,
    defaultValue: settings.lastUsedContextWindow ?? "1m",
  });
  updated = syncToggleOption(updated, {
    id: "fast",
    name: "Fast Mode",
    category: FAST_MODE_OPTION_CATEGORY,
    description: "Faster responses on supported models",
    options: fastModeOptions,
    defaultValue:
      settings.lastUsedFastMode == null
        ? "off"
        : settings.lastUsedFastMode
          ? "on"
          : "off",
  });

  return updated;
}
