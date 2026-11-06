import { describe, expect, it } from "vitest";
import {
  appendRichOutputPrompt,
  RICH_OUTPUT_PROMPT_LEAD,
} from "./rich-output-prompt";

const PROJECT_URL = "https://us.posthog.com/project/2";
const LEGACY_TAG_PROMPT = `Embed the PostHog objects behind your conclusions as XML tags, the same convention as \`<file path="..."/>\` attachments. Every tag is a live reference the app resolves when shown - never restate the object's data in your text, and never put tags inside code fences.
- Inline reference: \`<kind id="...">short human label</kind>\` inside a sentence, e.g. \`The <insight id="9pQx3">checkout funnel</insight> dropped after <flag id="42">new-checkout-flow</flag> rolled out.\` Kinds: insight, dashboard, error, replay, flag, experiment, survey, ticket, report, trace, eval, event, cohort, action, person. Use the object's id (insights: the short id; feature flags: the numeric id, falling back to the key; Inbox reports: the report uuid; persons: the uuid). It renders as a chip with a live hover preview that opens the object in PostHog.
- Inline SQL: \`<hogql label="signups today">SELECT count() FROM events WHERE ...</hogql>\` - the SQL is the tag body, the label is what the sentence shows. Hovering runs the query live; clicking opens the SQL editor.
- Full-size chart, for any numeric or time-series answer (always prefer this over a markdown table): a saved insight \`<insight id="9pQx3" display="block"/>\` or a query \`<hogql display="block" title="Daily active users, last 7 days" caption="optional context">SELECT ...</hogql>\`. The chart executes live on every view. Include the time range in the title, and keep blank lines out of the SQL body.
- Some PostHog MCP query tools render their result as an interactive chart in the conversation, and the tool result says so. When the tool result says the user already sees the result as an interactive view, do not embed the same data again as a \`<hogql>\` chart; write the conclusion in text and let that view carry the data. When it does not, the tool renders nothing on its own, so follow the full-size chart rule above.
- Recording card: \`<replay id="<session_id>" display="block"/>\` renders the recording's details with a link into PostHog's player. Use it when a specific session is the evidence.`;

function count(text: string, part: string): number {
  return text.split(part).length - 1;
}

describe("appendRichOutputPrompt", () => {
  it.each(["slack", "posthog_ai", "unknown"])(
    "removes existing rich-output guidance for %s",
    (interactionOrigin) => {
      const basePrompt = "Answer clearly.";
      const desktopPrompt = appendRichOutputPrompt(basePrompt);
      const legacyPrompt = `${basePrompt}\n\n## Rich output in replies\n${LEGACY_TAG_PROMPT}`;

      expect(appendRichOutputPrompt(desktopPrompt, interactionOrigin)).toBe(
        basePrompt,
      );
      expect(appendRichOutputPrompt(legacyPrompt, interactionOrigin)).toBe(
        basePrompt,
      );
      expect(appendRichOutputPrompt(basePrompt, interactionOrigin)).toBe(
        basePrompt,
      );
      expect(appendRichOutputPrompt(desktopPrompt, "desktop")).toBe(
        desktopPrompt,
      );
    },
  );

  it("teaches links into the session's project", () => {
    const prompt = appendRichOutputPrompt("Answer.", "desktop", PROJECT_URL);

    expect(prompt).toContain(`${PROJECT_URL}/insights/9pQx3`);
    expect(prompt).toContain(`${PROJECT_URL}/sql?open_query=`);
    expect(prompt).not.toContain("<PostHog host>");
  });

  it("replaces tag guidance an older client sent and keeps the sections around it", () => {
    const prompt = appendRichOutputPrompt(
      `Answer.\n\n## Rich output in replies\n${LEGACY_TAG_PROMPT}\n\n## Cloud\nKeep me.`,
      "desktop",
      PROJECT_URL,
    );

    expect(prompt).not.toContain("as XML tags");
    expect(prompt).toContain("Answer.\n\n## Cloud\nKeep me.");
    expect(count(prompt, RICH_OUTPUT_PROMPT_LEAD)).toBe(1);
  });

  it("keeps one block across layers, and a layer without a project keeps the known one", () => {
    const once = appendRichOutputPrompt("Answer.", "desktop", PROJECT_URL);
    const twice = appendRichOutputPrompt(once, "desktop", PROJECT_URL);

    expect(twice).toBe(once);
    expect(appendRichOutputPrompt(once)).toBe(once);
    expect(count(twice, "## Rich output in replies")).toBe(1);
  });
});
