import { hasAgentMention } from "@posthog/core/canvas/threadTimeline";
import { docTaskTitle } from "./docAgent";

export interface ThreadLine {
  author: string;
  content: string;
}

const AGENT_MENTION = /(^|\s)@agent\b/gi;

/** The post without the tag: the tag is for the page, not for the agent. */
export function stripAgentMention(content: string): string {
  return content.replace(AGENT_MENTION, "$1").replace(/\s+/g, " ").trim();
}

/**
 * The task a thread starts when someone first tags the agent.
 *
 * The agent gets the phrase the thread hangs off and everything said so far, so
 * a question that grew over three posts arrives whole. The title is the post
 * that tagged it.
 */
export function threadTaskInput(input: {
  anchorText: string;
  lines: ThreadLine[];
  question: string;
  docTitle: string;
}): { question: string; description: string } {
  const question = stripAgentMention(input.question);
  const transcript = input.lines
    .filter((line) => line.content.trim())
    .map((line) => `${line.author}: ${stripAgentMention(line.content)}`);
  const description = [
    question,
    "",
    input.anchorText.trim()
      ? `About this part of the page: “${input.anchorText.trim()}”`
      : null,
    transcript.length ? "Said in the thread so far:" : null,
    ...transcript,
    transcript.length || input.anchorText.trim() ? "" : null,
    "Answer in the thread, in a few lines. Do not edit the page.",
    `Asked from the page "${input.docTitle}".`,
  ]
    .filter((part) => part !== null)
    .join("\n");
  return {
    question: question || docTaskTitle(input.anchorText, "Question from a doc"),
    description,
  };
}

/**
 * What a data point run must end with. The adapter holds the model to this
 * shape, so even a run that never touches the tool ends as the answer.
 */
export const DOC_DATA_RESULT_SCHEMA: Record<string, unknown> = {
  type: "object",
  additionalProperties: false,
  required: ["status", "query", "label", "note"],
  properties: {
    status: {
      type: "string",
      enum: ["ok", "none"],
      description:
        "ok: the query answers the question. none: this project's data cannot answer it.",
    },
    query: {
      type: "string",
      description:
        "One HogQL SELECT that returns exactly one row and one column. Empty when status is none.",
    },
    label: {
      type: "string",
      description:
        "What the number counts, in a few words. The reader sees this on it.",
    },
    note: {
      type: "string",
      description:
        "One short line for the reader: a caveat, or with status none, why there is no answer. Empty otherwise.",
    },
  },
};

/**
 * The task behind a data point.
 *
 * The contract comes first and the question after it, so a small model reads
 * the job before the subject. Two ways in reach the page: the tool during the
 * run, and the schema-shaped final answer at its end.
 */
export function dataPointTaskInput(input: {
  question: string;
  requestId: string;
  docTitle: string;
}): { question: string; description: string } {
  const question = input.question.trim();
  const call = `call doc-data-point-submit {"request_id": "${input.requestId}", "query": "<your SELECT>", "label": "<what the number counts, in a few words>"}`;
  return {
    question,
    description: [
      `A page asks for one number: "${question}".`,
      "",
      "Write one HogQL SELECT that returns exactly one row and one column, and run it once with the PostHog SQL query tool. Do not browse recordings, insights, or dashboards; do not build or save anything.",
      `Hand the query in through the PostHog MCP \`exec\` tool: \`${call}\`. Run \`info doc-data-point-submit\` first if you need the schema. If it answers ok: false, fix the query and call it again.`,
      `request_id: ${input.requestId}`,
      'End your reply as the JSON object {"status", "query", "label", "note"}: status "ok" with the query, or status "none" with a note when the project\'s data cannot answer. Nothing else in the reply.',
      "",
      `Asked from the page "${input.docTitle}".`,
    ].join("\n"),
  };
}

/**
 * The standing instructions of a loop that watches a section of a page.
 *
 * The loop runs on a schedule with no person in the room, so the prompt says
 * what a report is: short, about change, with the queries it stands on.
 */
export function watchLoopInstructions(input: {
  anchorText: string;
  docTitle: string;
}): string {
  return [
    `Watch this part of the page "${input.docTitle}":`,
    `“${input.anchorText.trim()}”`,
    "",
    "On every run, check whether this project's data still supports it. Report in at most six lines:",
    "what holds, what changed since your last report, and one number for each claim, each cited",
    'as <hogql label="what it counts">SELECT ...</hogql>. Do not edit the page. Do not build or save',
    "an insight. If nothing changed, say so in one line.",
  ].join("\n");
}

export { hasAgentMention };
