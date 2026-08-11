// biome-ignore lint/suspicious/noControlCharactersInRegex: ESC is required to strip ANSI sequences
const ANSI_RE = /\x1b\[[0-9;]*[A-Za-z]/g;

export function stripAnsi(text: string): string {
  return text.replace(ANSI_RE, "");
}

function processOutput(lines: string[], chunk: string): string[] {
  const next = [...lines];
  const parts = chunk.split("\n");

  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    const crSegments = part.split("\r");
    const lastSegment = crSegments[crSegments.length - 1];

    if (i === 0 && next.length > 0) {
      if (crSegments.length > 1) {
        next[next.length - 1] = lastSegment;
      } else {
        next[next.length - 1] += lastSegment;
      }
    } else {
      next.push(lastSegment);
    }
  }

  return next;
}

export function appendOutputChunk(lines: string[], rawChunk: string): string[] {
  return processOutput(lines, stripAnsi(rawChunk));
}
