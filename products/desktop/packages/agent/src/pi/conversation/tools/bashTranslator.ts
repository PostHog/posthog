import type { AgentToolCallContent } from "@posthog/shared";
import type { PiToolTranslator } from "../toolTranslator";

export const bashTranslator: PiToolTranslator = ({ resultContent }) => {
  const outputText = resultContent
    ?.filter((block) => block.type === "text")
    .map((block) => block.text)
    .join("");

  if (!outputText) {
    return {};
  }

  const content: AgentToolCallContent[] = [
    {
      type: "content",
      content: { type: "text", text: outputText },
    },
  ];

  return { content };
};
