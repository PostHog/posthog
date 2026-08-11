import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { isSelectGroup } from "@posthog/shared";

function stripModelOptions(
  option: SessionConfigOption,
  isStripped: (value: string) => boolean,
): SessionConfigOption {
  if (option.type !== "select") return option;

  if (isSelectGroup(option.options)) {
    const options = option.options.map((group) => ({
      ...group,
      options: group.options.filter((model) => !isStripped(model.value)),
    }));
    return {
      ...option,
      options,
      currentValue: isStripped(option.currentValue)
        ? (options.flatMap((group) => group.options)[0]?.value ?? "")
        : option.currentValue,
    };
  }

  const options = option.options.filter((model) => !isStripped(model.value));
  return {
    ...option,
    options,
    currentValue: isStripped(option.currentValue)
      ? (options[0]?.value ?? "")
      : option.currentValue,
  };
}

export function stripGlmModelOption(
  option: SessionConfigOption,
): SessionConfigOption {
  return stripModelOptions(option, (value) =>
    value.toLowerCase().includes("glm"),
  );
}

export function stripDeepseekModelOption(
  option: SessionConfigOption,
): SessionConfigOption {
  return stripModelOptions(option, (value) =>
    value.toLowerCase().includes("deepseek"),
  );
}

export function stripKimiModelOption(
  option: SessionConfigOption,
): SessionConfigOption {
  return stripModelOptions(option, (value) => value === "moonshotai/kimi-k3");
}
