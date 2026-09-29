import { OBJECT_TAG_PROMPT_KIND_LIST } from "./objectTagKinds.generated";

const TAGS_INTRO = `Embed the PostHog objects behind your conclusions as XML tags, the same convention as \`<file path="..."/>\` attachments. Every tag is a live reference the app resolves when shown - never restate the object's data in your text, and never put tags inside code fences.`;

const INLINE_REFERENCE_RULE = `- Inline reference: \`<kind id="...">short human label</kind>\` inside a sentence, e.g. \`The <insight id="9pQx3">checkout funnel</insight> dropped after <flag id="42">new-checkout-flow</flag> rolled out.\` Kinds: ${OBJECT_TAG_PROMPT_KIND_LIST}. Use the object's id (insights: the short id; feature flags: the numeric id, falling back to the key; Inbox reports: the report uuid; persons: the uuid). It renders as a chip with a live hover preview that opens the object in PostHog.`;

const INLINE_SQL_RULE = `- Inline SQL: \`<hogql label="signups today">SELECT count() FROM events WHERE ...</hogql>\` - the SQL is the tag body, the label is what the sentence shows. Hovering runs the query live; clicking opens the SQL editor.`;

const FULL_SIZE_CHART_RULE = `- Full-size chart, for any numeric or time-series answer (always prefer this over a markdown table): a saved insight \`<insight id="9pQx3" display="block"/>\` or a query \`<hogql display="block" title="Daily active users, last 7 days" caption="optional context">SELECT ...</hogql>\`. The chart executes live on every view. Include the time range in the title, and keep blank lines out of the SQL body.`;

const INTERACTIVE_VIEW_RULE = `- Some PostHog MCP query tools render their result as an interactive chart in the conversation, and the tool result says so. When the tool result says the user already sees the result as an interactive view, do not embed the same data again as a \`<hogql>\` chart; write the conclusion in text and let that view carry the data. When it does not, the tool renders nothing on its own, so follow the full-size chart rule above.`;

const RECORDING_CARD_RULE = `- Recording card: \`<replay id="<session_id>" display="block"/>\` renders the recording's details with a link into PostHog's player. Use it when a specific session is the evidence.`;

// PostHog AI folds every tool call into a collapsed work log, so it inverts INTERACTIVE_VIEW_RULE.
const ANSWER_CHARTS_RULE = `- The app folds your tool calls into a collapsed work log, so the user does not see tool results, even when a tool result says the user already sees it as an interactive view. Present each result the user asked for in your final reply as a full-size chart, next to the sentence that explains it. Embed only the results that answer the request, not the queries you ran to explore the data, inspect a schema, or check a number.`;

/**
 * Prompt block teaching an agent the object-tag vocabulary the desktop
 * renders as live references (chips, hover previews, chart cards). Shared by
 * every agent runtime so its syntax stays in sync with what `remarkObjectTags`
 * parses; the kind list itself is generated from the registry
 * (posthog/object_tags/kinds.py) so the prompt cannot drift from what the
 * renderers understand.
 */
export const RICH_OUTPUT_TAGS_PROMPT = [
  TAGS_INTRO,
  INLINE_REFERENCE_RULE,
  INLINE_SQL_RULE,
  FULL_SIZE_CHART_RULE,
  INTERACTIVE_VIEW_RULE,
  RECORDING_CARD_RULE,
].join("\n");

/** The PostHog AI variant: the agent presents the requested results as charts in its answer. */
export const ANSWER_CHARTS_TAGS_PROMPT = [
  TAGS_INTRO,
  INLINE_REFERENCE_RULE,
  INLINE_SQL_RULE,
  FULL_SIZE_CHART_RULE,
  ANSWER_CHARTS_RULE,
].join("\n");

const SECTION_HEADING = "\n\n## Rich output in replies\n";

function withSection(prompt: string, section: string): string {
  return prompt.includes(section)
    ? prompt
    : `${prompt}${SECTION_HEADING}${section}`;
}

export function appendRichOutputPrompt(
  prompt: string,
  interactionOrigin?: string | null,
  options: { answerCharts?: boolean } = {},
): string {
  if (interactionOrigin === "posthog_ai" && options.answerCharts) {
    return withSection(prompt, ANSWER_CHARTS_TAGS_PROMPT);
  }
  if (
    interactionOrigin &&
    interactionOrigin !== "desktop" &&
    interactionOrigin !== "signal_report"
  ) {
    return prompt
      .replaceAll(`${SECTION_HEADING}${RICH_OUTPUT_TAGS_PROMPT}`, "")
      .replaceAll(RICH_OUTPUT_TAGS_PROMPT, "");
  }
  return withSection(prompt, RICH_OUTPUT_TAGS_PROMPT);
}
