import type {
  EditToolDetails,
  EditToolInput,
} from "@earendil-works/pi-coding-agent";
import type {
  AgentToolCallContent,
  AgentToolCallLocation,
} from "@posthog/shared";
import type { PiToolTranslator } from "../toolTranslator";

export const editTranslator: PiToolTranslator = ({
  arguments: rawArguments,
  resultContent,
  details: rawDetails,
}) => {
  const args = rawArguments as EditToolInput | undefined;
  const details = rawDetails as EditToolDetails | undefined;

  const locations: AgentToolCallLocation[] | undefined = args?.path
    ? [{ path: args.path, line: details?.firstChangedLine }]
    : undefined;

  if (args?.path && args.edits && args.edits.length > 0) {
    const diff: AgentToolCallContent = {
      type: "diff",
      path: args.path,
      oldText: args.edits.map((edit) => edit.oldText).join("\n"),
      newText: args.edits.map((edit) => edit.newText).join("\n"),
    };

    return { locations, content: [diff] };
  }

  if (args?.path && details?.diff) {
    const diff: AgentToolCallContent = {
      type: "diff",
      path: args.path,
      newText: details.diff,
    };

    return { locations, content: [diff] };
  }

  const textContent = resultContent
    ?.filter((block) => block.type === "text")
    .map((block) => ({
      type: "content" as const,
      content: { type: "text" as const, text: block.text },
    }));

  return {
    locations,
    content: textContent && textContent.length > 0 ? textContent : undefined,
  };
};
