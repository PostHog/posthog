/**
 * Prompt block teaching an agent the object-tag vocabulary the desktop
 * renders as live references (chips, hover previews, chart cards). Shared by
 * every agent runtime so its syntax stays in sync with what `remarkObjectTags`
 * parses.
 */
export const RICH_OUTPUT_TAGS_PROMPT = `Embed the PostHog objects behind your conclusions as XML tags, the same convention as \`<file path="..."/>\` attachments. Every tag is a live reference the app resolves when shown - never restate the object's data in your text, and never put tags inside code fences.
- Inline reference: \`<kind id="...">short human label</kind>\` inside a sentence, e.g. \`The <insight id="9pQx3">checkout funnel</insight> dropped after <flag id="42">new-checkout-flow</flag> rolled out.\` Kinds: insight, dashboard, error, replay, flag, experiment, survey, ticket, trace, eval, event, cohort, action, person. Use the object's id (insights: the short id; feature flags: the numeric id, falling back to the key; persons: the uuid). It renders as a chip with a live hover preview that opens the object in PostHog.
- Inline SQL: \`<hogql label="signups today">SELECT count() FROM events WHERE ...</hogql>\` - the SQL is the tag body, the label is what the sentence shows. Hovering runs the query live; clicking opens the SQL editor.
- Full-size chart, for any numeric or time-series answer (always prefer this over a markdown table): a saved insight \`<insight id="9pQx3" display="block"/>\` or a query \`<hogql display="block" title="Daily active users, last 7 days" caption="optional context">SELECT ...</hogql>\`. The chart executes live on every view. Include the time range in the title, and keep blank lines out of the SQL body.
- Recording card: \`<replay id="<session_id>" display="block"/>\` renders the recording's details with a link into PostHog's player. Use it when a specific session is the evidence.`;

export function appendRichOutputPrompt(prompt: string): string {
  if (prompt.includes(RICH_OUTPUT_TAGS_PROMPT)) {
    return prompt;
  }
  return `${prompt}\n\n## Rich output in replies\n${RICH_OUTPUT_TAGS_PROMPT}`;
}
