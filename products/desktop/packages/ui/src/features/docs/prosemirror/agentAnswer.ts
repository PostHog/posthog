import { parseObjectTags } from "@posthog/core/inbox/objectTags";
import type { JSONContent } from "@tiptap/core";

/** A query the page may run: one SELECT, whole, nothing elided. */
function isRunnableQuery(query: string): boolean {
  const cleaned = query.trim().replace(/;\s*$/, "");
  return (
    /^(with|select)\b/i.test(cleaned) &&
    !cleaned.includes(";") &&
    !/(^|[^.])\.\.\.|…/.test(cleaned)
  );
}

/**
 * What the agent said, as page content.
 *
 * A query it cited becomes a live data point in the sentence; any other object
 * it named becomes its name. Paragraph breaks are kept, markup is not: the page
 * takes the words, never the agent's markup.
 */
export function agentAnswerToContent(text: string): JSONContent[] {
  const paragraphs: JSONContent[] = [];
  for (const block of text.split(/\n\s*\n/)) {
    const inline: JSONContent[] = [];
    const pushText = (words: string) => {
      const last = inline[inline.length - 1];
      if (last?.type === "text") last.text = `${last.text}${words}`;
      else inline.push({ type: "text", text: words });
    };
    for (const segment of parseObjectTags(block.trim())) {
      if (segment.type === "tag") {
        // A query the agent only sketched (an ellipsis, a fragment) becomes its
        // label as words: the page never keeps a query it cannot run.
        if (segment.ref.kind === "hogql" && isRunnableQuery(segment.ref.id)) {
          inline.push({
            type: "dataValue",
            attrs: {
              query: segment.ref.id.trim().replace(/;\s*$/, ""),
              label: segment.ref.label === "SQL query" ? "" : segment.ref.label,
              note: "",
              requestId: "",
            },
          });
          continue;
        }
        if (segment.ref.label) pushText(segment.ref.label);
        continue;
      }
      const words = segment.value.replace(/\s*\n\s*/g, " ");
      if (words) pushText(words);
    }
    if (inline.length) paragraphs.push({ type: "paragraph", content: inline });
  }
  return paragraphs;
}
