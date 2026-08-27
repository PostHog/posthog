import { defineTool } from "@earendil-works/pi-coding-agent";
import { AGENT_FLOW_HANDOFF_TOOL } from "@posthog/shared";
import { Type } from "typebox";

export interface HandoffSubmission {
  title: string;
  markdown: string;
}

/**
 * Guidelines, not a template: the step decides the shape of its own document.
 */
export const HANDOFF_GUIDANCE = `How to write the handoff:
- Write for the next agent. That agent did not see your work and cannot ask you questions.
- Carry what the next agent cannot rebuild cheaply: what you concluded and why, what you changed and where, what you tried that did not work, and what is still open.
- Keep the facts a reader must act on: file paths, symbol names, commands, numbers, links.
- Leave out a report of your own process, and leave out what the task already says.
- Choose your own structure and length. Match them to the work.`;

export const HANDOFF_REMINDER = `You did not submit a handoff. Call the ${AGENT_FLOW_HANDOFF_TOOL} tool now with your handoff document, then end your turn.`;

export function createHandoffTool(
  onSubmit: (submission: HandoffSubmission) => void,
) {
  return defineTool({
    name: AGENT_FLOW_HANDOFF_TOOL,
    label: "Submit handoff",
    description:
      "Submit your handoff as one markdown document. Call this once, at the end of your turn. The document is stored for the user to read and comment on, and it is what the next step of the flow receives.",
    promptSnippet:
      "submit_handoff: hand your result to the next step as a markdown document",
    parameters: Type.Object({
      title: Type.String({
        description: "Short title for the document, in sentence case",
      }),
      markdown: Type.String({
        description: "The handoff document, in markdown",
      }),
    }),
    async execute(_toolCallId, params) {
      const markdown = params.markdown.trim();
      if (!markdown) {
        throw new Error("The handoff document is empty.");
      }
      onSubmit({ title: params.title.trim() || "Handoff", markdown });
      return {
        content: [
          {
            type: "text" as const,
            text: "Handoff recorded. End your turn now.",
          },
        ],
        details: {},
      };
    },
  });
}
