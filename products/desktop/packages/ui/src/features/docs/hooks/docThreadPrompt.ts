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
 * The task behind a data point.
 *
 * The contract comes first and the question after it, so a small model reads
 * the job before the subject. The tool is the only way the answer reaches the page.
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
      "When the project's data cannot answer, call it with status none and a note that says why. Reply with one short line for the people on the page. Do not put the query in the reply.",
      "",
      `Asked from the page "${input.docTitle}".`,
    ].join("\n"),
  };
}

/**
 * The task that compiles a hypothesis into a watch brief.
 *
 * The contract comes first and the claim after it, so a small model reads the
 * job before the subject. The tool is the only way the brief reaches the page.
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
      "Use the watching-doc-hypotheses skill. Compile the claim into a brief: the claim in one sentence, what confirms it, what refutes it, up to four evidence queries (each one HogQL SELECT returning one number, or a date and a number per row; run each once with the PostHog SQL query tool), and up to six short lines on what in this project you think is related to the claim (context for a scout, which decides on its own where to look). Do not build or save anything.",
      `Hand the brief in through the PostHog MCP \`exec\` tool: \`${call}\`. Run \`info doc-watch-brief-submit\` first if you need the schema. If it answers ok: false, fix the failing evidence query and call it again.`,
      `request_id: ${input.requestId}`,
      "Reply with one short line for the people on the page. Do not put the brief in the reply.",
      "",
      `Asked from the page "${input.docTitle}".`,
    ].join("\n"),
  };
}

export { hasAgentMention };
