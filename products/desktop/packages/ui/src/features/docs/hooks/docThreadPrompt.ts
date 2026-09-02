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
        "One HogQL SELECT. One cell for a number, a date column and a number column for a trend, anything else for a table. Empty when status is none.",
    },
    label: {
      type: "string",
      description: "What it shows, in a few words. The reader sees this on it.",
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
  const call = `call doc-data-point-submit {"request_id": "${input.requestId}", "query": "<your SELECT>", "label": "<what it shows, in a few words>"}`;
  return {
    question,
    description: [
      `A page asks for data: "${question}".`,
      "",
      "Write one HogQL SELECT and run it once with the PostHog SQL query tool. The page draws the result by its shape: one cell as a number in the sentence, a date column with a number column as a sparkline, anything else as a chart block. Do not browse recordings, insights, or dashboards; do not build or save anything.",
      `Hand the query in through the PostHog MCP \`exec\` tool: \`${call}\`. Run \`info doc-data-point-submit\` first if you need the schema. If it answers ok: false, fix the query and call it again.`,
      `request_id: ${input.requestId}`,
      'End your reply as the JSON object {"status", "query", "label", "note"}: status "ok" with the query, or status "none" with a note when the project\'s data cannot answer. Nothing else in the reply.',
      "",
      `Asked from the page "${input.docTitle}".`,
    ].join("\n"),
  };
}

/**
 * What a watch run must end with. The adapter holds the model to this shape,
 * so even a run that never touches the tool ends as the brief.
 */
export const DOC_WATCH_RESULT_SCHEMA: Record<string, unknown> = {
  type: "object",
  additionalProperties: false,
  required: ["claim", "confirms", "refutes", "evidence", "signals"],
  properties: {
    claim: {
      type: "string",
      description: "The hypothesis in one sentence, as the page states it.",
    },
    confirms: {
      type: "string",
      description: "What in the data would confirm it, in one line.",
    },
    refutes: {
      type: "string",
      description: "What in the data would refute it, in one line.",
    },
    evidence: {
      type: "array",
      maxItems: 4,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["label", "query"],
        properties: {
          label: { type: "string", description: "What the number counts." },
          query: {
            type: "string",
            description:
              "One HogQL SELECT that returns one number, or a date and a number per row.",
          },
        },
      },
    },
    signals: {
      type: "array",
      maxItems: 6,
      items: { type: "string" },
      description:
        "Short lines naming what a scout should follow: events, flags, experiments, error issues, replay filters.",
    },
  },
};

/**
 * The task that compiles a hypothesis into a watch brief.
 *
 * The contract comes first and the claim after it, so a small model reads the
 * job before the subject. Two ways in reach the page: the tool during the run,
 * and the schema-shaped final answer at its end.
 */
export function watchTaskInput(input: {
  anchorText: string;
  requestId: string;
  docTitle: string;
}): { question: string; description: string } {
  const claim = input.anchorText.trim().replace(/\s+/g, " ");
  const call = `call doc-watch-brief-submit {"request_id": "${input.requestId}", "claim": "<the claim in one sentence>", "confirms": "<what would confirm it>", "refutes": "<what would refute it>", "evidence": [{"label": "<what it counts>", "query": "<SELECT>"}], "signals": ["<what to follow>"]}`;
  return {
    question: docTaskTitle(claim, "Watch a hypothesis"),
    description: [
      `A page asks you to watch this hypothesis: “${claim}”.`,
      "",
      "Use the watching-doc-hypotheses skill. Compile the claim into a brief: the claim in one sentence, what confirms it, what refutes it, up to four evidence queries (each one HogQL SELECT returning one number, or a date and a number per row; run each once with the PostHog SQL query tool), and up to six signals a scout should follow (real events, flags, experiments, error issues, replay filters in this project). Do not build or save anything.",
      `Hand the brief in through the PostHog MCP \`exec\` tool: \`${call}\`. Run \`info doc-watch-brief-submit\` first if you need the schema. If it answers ok: false, fix the failing evidence query and call it again.`,
      `request_id: ${input.requestId}`,
      'End your reply as the JSON object {"claim", "confirms", "refutes", "evidence", "signals"}. Nothing else in the reply.',
      "",
      `Asked from the page "${input.docTitle}".`,
    ].join("\n"),
  };
}

export { hasAgentMention };
