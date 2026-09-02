import type {
  SessionConfigOption,
  SessionConfigSelectGroup,
  SessionConfigSelectOption,
} from "@agentclientprotocol/sdk";
import { DEFAULT_OPTION_META_KEY } from "@posthog/shared";
import { EFFORT_LEVEL_LABELS } from "@posthog/shared/domain-types";
import { reasoningEffortsForModel } from "@posthog/shared/model-catalog";

interface ReasoningEffortOption {
  value: string;
  name: string;
  _meta?: Record<string, unknown>;
}

// "high" is the effort this app starts codex sessions with (see the preview
// config and workspace-server defaults), so the picker badges it as default.
const DEFAULT_CODEX_EFFORT = "high";

export function getReasoningEffortOptions(
  modelId: string,
): ReasoningEffortOption[] {
  return reasoningEffortsForModel("codex", modelId).map((value) => ({
    value,
    name: EFFORT_LEVEL_LABELS[value],
    ...(value === DEFAULT_CODEX_EFFORT
      ? { _meta: { [DEFAULT_OPTION_META_KEY]: true } }
      : {}),
  }));
}

export function formatCodexModelName(value: string): string {
  return value.toLowerCase();
}

export function modelIdFromConfigOptions(
  configOptions: SessionConfigOption[] | null | undefined,
): string | undefined {
  const modelOption = configOptions?.find((o) => o.category === "model");
  return typeof modelOption?.currentValue === "string"
    ? modelOption.currentValue
    : undefined;
}

export function normalizeCodexConfigOptions(
  configOptions: SessionConfigOption[] | null | undefined,
): SessionConfigOption[] | null | undefined {
  if (!configOptions) return configOptions;
  const formatOption = (
    opt: SessionConfigSelectOption,
  ): SessionConfigSelectOption => ({
    ...opt,
    name: formatCodexModelName(opt.value),
  });
  return configOptions.map((option) => {
    if (option.category !== "model" || option.type !== "select") return option;
    const options = option.options;
    if (options.length === 0) return option;
    const isGroup = "group" in options[0];
    return {
      ...option,
      options: isGroup
        ? (options as SessionConfigSelectGroup[]).map((group) => ({
            ...group,
            options: group.options.map(formatOption),
          }))
        : (options as SessionConfigSelectOption[]).map(formatOption),
    } as SessionConfigOption;
  });
}
