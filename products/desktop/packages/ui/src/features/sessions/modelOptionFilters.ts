import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { isSelectGroup } from "@posthog/shared";

export function stripGlmModelOption(
  option: SessionConfigOption,
): SessionConfigOption {
  if (option.type !== "select") return option;

  if (isSelectGroup(option.options)) {
    return {
      ...option,
      options: option.options.map((group) => ({
        ...group,
        options: group.options.filter(
          (o) => !o.value.toLowerCase().includes("glm"),
        ),
      })),
    };
  }

  return {
    ...option,
    options: option.options.filter(
      (o) => !o.value.toLowerCase().includes("glm"),
    ),
  };
}

export function stripKimiModelOption(
  option: SessionConfigOption,
): SessionConfigOption {
  if (option.type !== "select") return option;

  if (isSelectGroup(option.options)) {
    const options = option.options.map((group) => ({
      ...group,
      options: group.options.filter(
        (model) => model.value !== "moonshotai/kimi-k3",
      ),
    }));
    return {
      ...option,
      options,
      currentValue:
        option.currentValue === "moonshotai/kimi-k3"
          ? (options.flatMap((group) => group.options)[0]?.value ?? "")
          : option.currentValue,
    };
  }

  const options = option.options.filter(
    (model) => model.value !== "moonshotai/kimi-k3",
  );
  return {
    ...option,
    options,
    currentValue:
      option.currentValue === "moonshotai/kimi-k3"
        ? (options[0]?.value ?? "")
        : option.currentValue,
  };
}
