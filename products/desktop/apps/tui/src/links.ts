import {
  getOsc8LinkAtColumn,
  stripTerminalSequences,
  visibleWidth,
} from "@earendil-works/pi-tui";

const BARE_URL = /https?:\/\/[^\s<>"'`]+/g;
// Sentence punctuation that usually follows a link rather than belonging to it.
const TRAILING = /[.,;:!?'"]+$/;

// Only web links open: the agent's text can carry any scheme, and file: or app schemes would launch local programs.
export function isWebUrl(url: string): boolean {
  try {
    const { protocol } = new URL(url);
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

// Drops trailing punctuation and a closing bracket the link did not open, as in "(see https://x.com)".
function trimUrl(url: string): string {
  let trimmed = url.replace(TRAILING, "");
  for (const [open, close] of [
    ["(", ")"],
    ["[", "]"],
  ]) {
    while (
      trimmed.endsWith(close) &&
      trimmed.split(close).length > trimmed.split(open).length
    )
      trimmed = trimmed.slice(0, -1).replace(TRAILING, "");
  }
  return trimmed;
}

// The web link under a cell of a rendered line, 0-based: an OSC 8 hyperlink first, then a URL written out in the text.
export function linkAt(line: string, column: number): string | null {
  const hyperlink = getOsc8LinkAtColumn(line, column);
  if (hyperlink) return isWebUrl(hyperlink) ? hyperlink : null;
  const text = stripTerminalSequences(line);
  for (const match of text.matchAll(BARE_URL)) {
    const url = trimUrl(match[0]);
    const start = visibleWidth(text.slice(0, match.index));
    if (column >= start && column < start + visibleWidth(url))
      return isWebUrl(url) ? url : null;
  }
  return null;
}
