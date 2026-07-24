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
