export function basename(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, "");
  const idx = Math.max(trimmed.lastIndexOf("/"), trimmed.lastIndexOf("\\"));
  return idx >= 0 ? trimmed.slice(idx + 1) || trimmed : trimmed;
}

export interface ParsedCommandLine {
  name: string;
  args: string | undefined;
}

const COMMAND_LINE_REGEX = /^\/(\S+)(?:\s+(.*))?$/;

export function parseCommandLine(text: string): ParsedCommandLine | null {
  const match = text.match(COMMAND_LINE_REGEX);
  if (!match) return null;
  return { name: match[1], args: match[2] };
}
