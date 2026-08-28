import type {
  SessionConfigOption,
  SessionConfigSelectGroup,
  SessionConfigSelectOption,
} from "@agentclientprotocol/sdk";
import { DEFAULT_OPTION_META_KEY } from "@posthog/shared";
import { EFFORT_LEVEL_LABELS } from "@posthog/shared/domain-types";

interface ReasoningEffortOption {
  value: string;
  name: string;
  _meta?: Record<string, unknown>;
}

// "high" is the effort this app starts codex sessions with (see the preview
// config and workspace-server defaults), so the picker badges it as default.
const CODEX_REASONING_EFFORT_OPTIONS: ReasoningEffortOption[] = [
  { value: "low", name: EFFORT_LEVEL_LABELS.low },
  { value: "medium", name: EFFORT_LEVEL_LABELS.medium },
  {
    value: "high",
    name: EFFORT_LEVEL_LABELS.high,
    _meta: { [DEFAULT_OPTION_META_KEY]: true },
  },
];

// OpenAI's `reasoning_effort` exposes an "extra high" tier on the gpt-5.5 and
// gpt-5.6 families. GPT-5.6 also supports the "max" tier. Older models top out
// at "high".
export function supportsXhighEffort(modelId: string): boolean {
  const id = modelId.toLowerCase();
  return id.includes("gpt-5.5") || id.includes("gpt-5.6");
}

export function supportsMaxEffort(modelId: string): boolean {
  return modelId.toLowerCase().includes("gpt-5.6");
}

export function getReasoningEffortOptions(
  modelId: string,
): ReasoningEffortOption[] {
  const options = [...CODEX_REASONING_EFFORT_OPTIONS];
  if (supportsXhighEffort(modelId)) {
    options.push({ value: "xhigh", name: EFFORT_LEVEL_LABELS.xhigh });
  }
  if (supportsMaxEffort(modelId)) {
    options.push({ value: "max", name: EFFORT_LEVEL_LABELS.max });
  }
  return options;
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
