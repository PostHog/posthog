import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import {
  type Adapter,
  adapterForModelId,
  flattenSelectOptions,
  formatModelId,
  isSelectGroup,
  selectOptionHarness,
} from "@posthog/shared";
import type { PiThinkingLevel } from "../pi-runtime/piSessionController";

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
 * A session-only Pi selection for a pick outside Pi's curated catalog. Pi
 * runs any gateway model, so the pick keeps its id; the thinking levels are
 * unknown, so the composer hides the thinking control.
 */
export function syntheticPiModelSelection(
  option: SessionConfigOption | undefined,
  value: string,
): {
  provider: "posthog";
  id: string;
  name: string;
  isDefault: boolean;
  contextWindow: number;
  thinkingLevels: PiThinkingLevel[];
} {
  const name =
    option?.type === "select"
      ? flattenSelectOptions(option.options).find(
          (entry) => entry.value === value,
        )?.name
      : undefined;
  return {
    provider: "posthog",
    id: value,
    name: name ?? formatModelId(value),
    isDefault: false,
    contextWindow: 0,
    thinkingLevels: [],
  };
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
