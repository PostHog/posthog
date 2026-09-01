import type {
  ReadToolDetails,
  ReadToolInput,
} from "@earendil-works/pi-coding-agent";
import type { AgentToolCallContent } from "@posthog/shared";
import type { PiToolTranslator } from "../toolTranslator";

export const readTranslator: PiToolTranslator = ({
  arguments: rawArguments,
  resultContent,
  details: rawDetails,
}) => {
  const args = rawArguments as ReadToolInput | undefined;
  const details = rawDetails as ReadToolDetails | undefined;

  const locations = args?.path ? [{ path: args.path }] : undefined;

  const textBlock = resultContent?.find((block) => block.type === "text");
  const content: AgentToolCallContent[] = [];

  if (textBlock && textBlock.type === "text") {
    let text = textBlock.text;

    if (details?.truncation?.truncated) {
      text = `${text}\n[truncated: showing ${details.truncation.outputLines} of ${details.truncation.totalLines} lines]`;
    }

    content.push({ type: "content", content: { type: "text", text } });
  }

  return {
    locations,
    content: content.length > 0 ? content : undefined,
  };
};
