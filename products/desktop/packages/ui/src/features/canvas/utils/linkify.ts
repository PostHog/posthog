const URL_PATTERN = /https?:\/\/[^\s<>]+/gi;

// Named links written as markdown `[label](https://url)` — the shape auto-posted
// thread messages use. Label excludes brackets and the URL excludes parens so
// the token boundaries are unambiguous (same reasoning as MENTION_PATTERN).
const MARKDOWN_LINK_PATTERN = /\[([^\][\n]+)\]\((https?:\/\/[^\s()]+)\)/gi;

export interface LinkTextSegment {
  type: "text";
  text: string;
}

export interface LinkUrlSegment {
  type: "link";
  text: string;
  href: string;
}

export type LinkSegment = LinkTextSegment | LinkUrlSegment;

/**
 * Trailing punctuation reads as prose, not part of the URL; a `)` is kept only
 * when it closes a paren opened inside the URL (e.g. Wikipedia paths).
 */
function trimTrailingPunctuation(url: string): string {
  let end = url.length;
  while (end > 0) {
    const char = url[end - 1] as string;
    if (".,;:!?'\"]}".includes(char)) {
      end--;
      continue;
    }
    if (char === ")") {
      const body = url.slice(0, end);
      const opens = body.split("(").length - 1;
      const closes = body.split(")").length - 1;
      if (closes > opens) {
        end--;
        continue;
      }
    }
    break;
  }
  return url.slice(0, end);
}

/**
 * Split plain text into text and http(s) link segments, in document order.
 * Markdown-style `[label](url)` tokens become links titled by their label;
 * bare URLs in the remaining text link as themselves.
 */
export function splitLinkSegments(text: string): LinkSegment[] {
  const segments: LinkSegment[] = [];
  let lastIndex = 0;
  MARKDOWN_LINK_PATTERN.lastIndex = 0;
  for (const match of text.matchAll(MARKDOWN_LINK_PATTERN)) {
    const index = match.index ?? 0;
    if (index > lastIndex) {
      segments.push(...splitBareUrlSegments(text.slice(lastIndex, index)));
    }
    segments.push({
      type: "link",
      text: match[1] ?? "",
      href: match[2] ?? "",
    });
    lastIndex = index + match[0].length;
  }
  if (lastIndex < text.length) {
    segments.push(...splitBareUrlSegments(text.slice(lastIndex)));
  }
  return segments;
}

function splitBareUrlSegments(text: string): LinkSegment[] {
  const segments: LinkSegment[] = [];
  let lastIndex = 0;
  URL_PATTERN.lastIndex = 0;
  for (const match of text.matchAll(URL_PATTERN)) {
    const url = trimTrailingPunctuation(match[0]);
    if (!url) continue;
    const index = match.index ?? 0;
    if (index > lastIndex) {
      segments.push({ type: "text", text: text.slice(lastIndex, index) });
    }
    segments.push({ type: "link", text: url, href: url });
    lastIndex = index + url.length;
  }
  if (lastIndex < text.length) {
    segments.push({ type: "text", text: text.slice(lastIndex) });
  }
  return segments;
}
