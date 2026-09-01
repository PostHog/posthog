import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import {
  type Adapter,
  adapterForModelId,
  flattenSelectOptions,
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
