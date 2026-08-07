// Mobile has no DOMParser, so this removes the meta tag at the string level
// rather than reusing the desktop DOM-based removal. The scan is attribute
// aware — a quoted ">" inside an attribute value does not end the tag, and
// http-equiv is read as a parsed attribute rather than matched as loose text —
// so it agrees with what an HTML tokenizer sees.

// Returns the index just past the ">" that closes the tag opened at `from`,
// skipping over quoted attribute values.
function tagEnd(html: string, from: number): number {
  let index = from;
  while (index < html.length) {
    const char = html[index];
    if (char === '"' || char === "'") {
      const closingQuote = html.indexOf(char, index + 1);
      // An unterminated quote swallows the rest of the document, exactly as a
      // tokenizer stuck in the attribute-value state would.
      if (closingQuote === -1) return html.length;
      index = closingQuote + 1;
      continue;
    }
    if (char === ">") return index + 1;
    index += 1;
  }
  return html.length;
}

const META_TAG = /<meta\b/gi;
const ATTRIBUTE = /([^\s/>=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]*)))?/g;

function isRefreshMeta(tag: string): boolean {
  ATTRIBUTE.lastIndex = "<meta".length;
  let attribute = ATTRIBUTE.exec(tag);
  while (attribute !== null) {
    const name = attribute[1].toLowerCase();
    const value = attribute[2] ?? attribute[3] ?? attribute[4] ?? "";
    if (name === "http-equiv" && value.trim().toLowerCase() === "refresh") {
      return true;
    }
    attribute = ATTRIBUTE.exec(tag);
  }
  return false;
}

export function removeAutomaticRedirects(html: string): string {
  META_TAG.lastIndex = 0;
  let kept = "";
  let copiedUpTo = 0;
  let stripped = false;
  let match = META_TAG.exec(html);
  while (match !== null) {
    const end = tagEnd(html, match.index + match[0].length);
    if (isRefreshMeta(html.slice(match.index, end))) {
      kept += html.slice(copiedUpTo, match.index);
      copiedUpTo = end;
      stripped = true;
    }
    META_TAG.lastIndex = end;
    match = META_TAG.exec(html);
  }
  return stripped ? kept + html.slice(copiedUpTo) : html;
}
