const ESC = "\u001b";
const RESETS = new RegExp(`${ESC}\\[(?:0|22)?m`, "g");

// Faint text stands in for opacity on panes without focus; a line's own resets would turn it off, so it is re-applied after each.
export function faint(line: string): string {
  return `${ESC}[2m${line.replace(RESETS, (reset) => `${reset}${ESC}[2m`)}${ESC}[22m`;
}
