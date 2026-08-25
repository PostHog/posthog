import type { FindToolInput } from "@earendil-works/pi-coding-agent";
import type { AgentToolCallLocation } from "@posthog/shared";
import type { PiToolTranslator } from "../toolTranslator";

export const findTranslator: PiToolTranslator = ({
  arguments: rawArguments,
  resultContent,
}) => {
  const args = rawArguments as FindToolInput | undefined;

  const locations: AgentToolCallLocation[] | undefined = args?.path
    ? [{ path: args.path }]
    : undefined;

  const content = resultContent
    ?.filter((block) => block.type === "text")
    .map((block) => ({
      type: "content" as const,
      content: { type: "text" as const, text: block.text },
    }));

  return {
    locations,
    content: content && content.length > 0 ? content : undefined,
  };
};
