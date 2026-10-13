import { OBJECT_LINK_PROMPT_PATH_LIST } from "./objectTagKinds.generated";

export const RICH_OUTPUT_PROMPT_HEADING = "## Rich output in replies";
export const RICH_OUTPUT_PROMPT_LEAD =
  "Link the PostHog objects behind your conclusions as Markdown links";

const FALLBACK_PROJECT_URL = "https://<PostHog host>/project/<project id>";
const BLOCK_END = String.raw`Use it when a specific session is the evidence\.`;
const BLOCK_BODY = String.raw`(?:(?!\n## )[\s\S])*?${BLOCK_END}`;
const OPTIONAL_HEADING = String.raw`(?:\n\n${RICH_OUTPUT_PROMPT_HEADING}\n)?`;
const LEGACY_TAG_BLOCK = new RegExp(
  `${OPTIONAL_HEADING}Embed the PostHog objects behind your conclusions as XML tags${BLOCK_BODY}`,
  "g",
);
const LINK_BLOCK = new RegExp(
  `${OPTIONAL_HEADING}${RICH_OUTPUT_PROMPT_LEAD}${BLOCK_BODY}`,
  "g",
);

export function getProjectWebUrl(
  appUrl: string,
  projectId: number | string,
): string {
  return `${appUrl.replace(/\/+$/, "")}/project/${projectId}`;
}

export function renderRichOutputPrompt(projectUrl?: string | null): string {
  const base = projectUrl?.replace(/\/+$/, "") || FALLBACK_PROJECT_URL;
  return `${RICH_OUTPUT_PROMPT_LEAD} to their pages in this project, ${base}. The app recognizes these links and shows each one as a live object, so never restate the object's data in your text, and never put the links inside code fences or inline code. A link to another host or project stays a plain link.
- Inline reference: \`[short human label](${base}/<path>)\` inside a sentence, e.g. \`The [checkout funnel](${base}/insights/9pQx3) dropped after [new-checkout-flow](${base}/feature_flags/42) rolled out.\` Paths: ${OBJECT_LINK_PROMPT_PATH_LIST}. Use the object's id (insights: the short id; feature flags: the numeric id, never the key; Inbox reports: the report uuid; persons: the uuid; events: the event definition uuid). When a tool result gives a \`_posthogUrl\` for the object, link to that URL. It renders as a chip with a live hover preview that opens the object in PostHog.
- Inline SQL: \`[signups today](${base}/sql?open_query=SELECT%20count()%20FROM%20events)\`. Percent-encode the SQL the way encodeURIComponent does: spaces as %20 (never +), and encode every %, #, &, +, ", <, >, [, ] and line break. Hovering runs the query live; clicking opens the SQL editor.
- Full-size chart, for any numeric or time-series answer (always prefer this over a markdown table): put the link to a saved insight or a SQL query alone in its own paragraph, with a blank line before and after it and not inside a list or table, e.g. \`[Daily active users, last 7 days](${base}/sql?open_query=SELECT%20...)\`. The link text is the chart title, so include the time range. An optional quoted link title adds a caption: \`[title](url "caption")\`. The chart executes live on every view.
- Some PostHog MCP query tools render their result as an interactive chart in the conversation, and the tool result says so. When the tool result says the user already sees the result as an interactive view, do not link the same query again as a chart; write the conclusion in text and let that view carry the data. When it does not, the tool renders nothing on its own, so follow the full-size chart rule above.
- Recording card: a link to \`${base}/replay/<session_id>\` alone in its own paragraph renders the recording's details with a link into PostHog's player. Use it when a specific session is the evidence.`;
}

export function appendRichOutputPrompt(
  prompt: string,
  interactionOrigin?: string | null,
  projectUrl?: string | null,
): string {
  const withoutLegacy = prompt.replace(LEGACY_TAG_BLOCK, "");
  if (
    interactionOrigin &&
    interactionOrigin !== "desktop" &&
    interactionOrigin !== "signal_report"
  ) {
    return withoutLegacy.replace(LINK_BLOCK, "");
  }
  if (!projectUrl && withoutLegacy.search(LINK_BLOCK) !== -1) {
    return withoutLegacy;
  }
  return `${withoutLegacy.replace(LINK_BLOCK, "")}\n\n${RICH_OUTPUT_PROMPT_HEADING}\n${renderRichOutputPrompt(projectUrl)}`;
}
