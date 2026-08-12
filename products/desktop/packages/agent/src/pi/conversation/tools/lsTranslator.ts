import type { LsToolInput } from "@earendil-works/pi-coding-agent";
import type {
  AgentToolCallContent,
  AgentToolCallLocation,
} from "@posthog/shared";
import type { PiToolTranslator } from "../toolTranslator";

export const lsTranslator: PiToolTranslator = ({
  arguments: args,
  resultContent,
}) => {
  const input = args as LsToolInput | undefined;

  const locations: AgentToolCallLocation[] = [];
  if (input?.path) {
    locations.push({ path: input.path });
  }

  const content: AgentToolCallContent[] = [];
  for (const block of resultContent ?? []) {
    if (block.type === "text") {
      content.push({
        type: "content",
        content: { type: "text", text: block.text },
      });
    }
  }

  return {
    locations: locations.length > 0 ? locations : undefined,
    content: content.length > 0 ? content : undefined,
  };
};
