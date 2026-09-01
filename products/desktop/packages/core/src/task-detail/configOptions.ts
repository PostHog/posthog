import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import {
  type Adapter,
  adapterForModelId,
  flattenSelectOptions,
  isSelectGroup,
  selectOptionHarness,
} from "@posthog/shared";

type RawOptionItem = {
  value?: string;
  options?: Array<{ value: string }>;
};

export function flattenConfigValues(option: SessionConfigOption): string[] {
  if (option.type !== "select") return [];
  return (option.options as RawOptionItem[]).flatMap((o) =>
    o.options ? o.options.map((g) => g.value) : o.value ? [o.value] : [],
  );
}

export function isValidConfigValue(
  option: SessionConfigOption | undefined,
  value: string,
): option is Extract<SessionConfigOption, { type: "select" }> {
  if (!option || option.type !== "select") return false;
  return flattenConfigValues(option).includes(value);
}

/**
 * Names the harness a model in a select option runs on. A model list that spans
 * harnesses stamps the harness on each option; the id shape is the fallback for
 * lists built before the stamp existed.
 */
export function harnessForModelValue(
  option: SessionConfigOption | undefined,
  value: string,
): Adapter | undefined {
  if (!option || option.type !== "select") return undefined;
  const entry = flattenSelectOptions(option.options).find(
    (candidate) => candidate.value === value,
  );
  if (!entry) return undefined;
  return selectOptionHarness(entry._meta) ?? adapterForModelId(value);
}

/**
 * The harness a model pick lands on while Pi is the current harness. Pi keeps
 * the pick when its catalog runs the model; otherwise the pick falls to the
 * model's own harness.
 */
export function resolvePiModelPick(
  piModelIds: readonly string[],
  option: SessionConfigOption | undefined,
  value: string,
): "pi" | Adapter {
  if (piModelIds.includes(value)) return "pi";
  return harnessForModelValue(option, value) ?? adapterForModelId(value);
}

/**
 * Narrows a model option that spans harnesses down to one harness. A picker
 * that cannot switch harness with the pick must not offer the other's models,
 * or the task runs a model its harness cannot serve. A list for a single
 * harness passes through untouched.
 */
export function modelOptionForHarness(
  option: SessionConfigOption | undefined,
  adapter: Adapter,
): SessionConfigOption | undefined {
  if (option?.type !== "select" || !isSelectGroup(option.options))
    return option;
  return {
    ...option,
    options: flattenSelectOptions(option.options).filter(
      (entry) => selectOptionHarness(entry._meta) === adapter,
    ),
  };
}
