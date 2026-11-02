import { stripTerminalSequences, visibleWidth } from "@earendil-works/pi-tui";

// The length of the escape sequence at index: CSI (ESC [ … final byte) or OSC (ESC ] … BEL or ESC \), else 0.
function escapeLength(line: string, index: number): number {
  if (line[index] !== "\u001b") return 0;
  const kind = line[index + 1];
  if (kind === "[") {
    let at = index + 2;
    while (at < line.length && !/[@-~]/.test(line[at])) at++;
    return at + 1 - index;
  }
  if (kind === "]") {
    for (let at = index + 2; at < line.length; at++) {
      if (line[at] === "\u0007") return at + 1 - index;
      if (line[at] === "\u001b" && line[at + 1] === "\\") return at + 2 - index;
    }
    return line.length - index;
  }
  return 0;
}

const graphemes = new Intl.Segmenter();

// A line cut at a column with its escapes in place, and the style codes met before the cut.
// Replaying those codes after a reset gives the style the line has at that column.
function cutAt(line: string, column: number): { head: string; styles: string } {
  let width = 0;
  let index = 0;
  let styles = "";
  while (index < line.length) {
    const length = escapeLength(line, index);
    if (length > 0) {
      const sequence = line.slice(index, index + length);
      if (sequence[1] === "[" && sequence.endsWith("m")) styles += sequence;
      index += length;
      continue;
    }
    const [grapheme] = graphemes.segment(line.slice(index));
    const cells = visibleWidth(grapheme.segment);
    if (width + cells > column) break;
    width += cells;
    index += grapheme.segment.length;
  }
  return { head: line.slice(0, index), styles };
}

// Draws the cells from start up to end in inverse video, as plain text, so a selection reads as one block.
// The selection replaces styled text, so the rest of the row gets back the style it had there, not one that leaked past it.
export function inverseCells(line: string, start: number, end: number): string {
  const head = cutAt(line, start).head;
  const rest = cutAt(line, end);
  const text = stripTerminalSequences(
    line.slice(head.length, rest.head.length),
  );
  if (!text) return line;
  return `${head}\u001b[0m\u001b[7m${text}\u001b[27m\u001b[0m${rest.styles}${line.slice(rest.head.length)}`;
}
