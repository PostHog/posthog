import type {
  GrepToolDetails,
  GrepToolInput,
} from "@earendil-works/pi-coding-agent";
import type {
  AgentToolCallContentBlock,
  AgentToolCallLocation,
} from "@posthog/shared";
import type { PiToolTranslator } from "../toolTranslator";

export const grepTranslator: PiToolTranslator = ({
  arguments: rawArguments,
  resultContent,
  details: rawDetails,
}) => {
  const args = rawArguments as GrepToolInput;
  const details = rawDetails as GrepToolDetails | undefined;

  const locations: AgentToolCallLocation[] = [];
  if (args?.path) {
    locations.push({ path: args.path });
  }

  const content: AgentToolCallContentBlock[] = [];
  const resultText = (resultContent ?? [])
    .filter((block) => block.type === "text")
    .map((block) => block.text)
    .join("\n");

  if (resultText) {
    content.push({
      type: "content",
      content: { type: "text", text: resultText },
    });
  }

  const notes: string[] = [];
  if (details?.matchLimitReached !== undefined) {
    notes.push(`Match limit reached at ${details.matchLimitReached} matches.`);
  }
  if (details?.linesTruncated) {
    notes.push("Some lines were truncated.");
  }
  if (notes.length > 0) {
    content.push({
      type: "content",
      content: { type: "text", text: notes.join(" ") },
    });
  }

  return {
    locations: locations.length > 0 ? locations : undefined,
    content: content.length > 0 ? content : undefined,
  };
};
