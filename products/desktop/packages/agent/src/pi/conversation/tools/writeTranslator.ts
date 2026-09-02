import type { WriteToolInput } from "@earendil-works/pi-coding-agent";
import type { PiToolTranslator } from "../toolTranslator";

export const writeTranslator: PiToolTranslator = ({ arguments: args }) => {
  const input = args as WriteToolInput;

  return {
    locations: [{ path: input.path }],
    content: [
      {
        type: "diff",
        path: input.path,
        oldText: null,
        newText: input.content,
      },
    ],
  };
};
