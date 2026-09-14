interface FenceState {
  inFence: boolean;
  fenceChar: string;
  fenceLen: number;
}

const NO_FENCE: FenceState = { inFence: false, fenceChar: "", fenceLen: 0 };

/**
 * Advance the fenced-code-block state machine by one line. A ``` / ~~~ line
 * opens a fence; it closes only on a line of the same marker char, at least as
 * long as the opener, followed by nothing but whitespace (CommonMark's close
 * rule). That stops a nested fence or a ```lang-style content line from closing
 * the block early. Shared by every fence-aware function here so the rule lives
 * in exactly one place.
 */
function stepFence(state: FenceState, line: string): FenceState {
  const trimmed = line.replace(/^ {0,3}/, "");
  const marker = /^(`{3,}|~{3,})/.exec(trimmed);
  if (!marker) return state;
  if (!state.inFence) {
    return {
      inFence: true,
      fenceChar: marker[1][0],
      fenceLen: marker[1].length,
    };
  }
  const closesFence =
    trimmed[0] === state.fenceChar &&
    marker[1].length >= state.fenceLen &&
    !/\S/.test(trimmed.slice(marker[1].length));
  return closesFence ? NO_FENCE : state;
}

/**
 * Split append-only markdown into top-level blocks at blank-line boundaries,
 * keeping fenced code blocks intact. Concatenating the result reproduces the
 * input exactly, so no text is ever dropped.
 *
 * During streaming the LAST element is the still-growing "tail"; everything
 * before it is stable (append-only text never rewrites an earlier block), so a
 * caller can render earlier blocks once and memoize them, re-parsing only the
 * tail on each token. That turns the per-token markdown cost from O(message)
 * into O(last block).
 */
export function splitMarkdownBlocks(src: string): string[] {
  if (src.length === 0) return [src];
  const blocks: string[] = [];
  const n = src.length;
  let blockStart = 0;
  let i = 0;
  let fence = NO_FENCE;

  while (i < n) {
    let nl = src.indexOf("\n", i);
    if (nl === -1) nl = n;
    const line = src.slice(i, nl);
    fence = stepFence(fence, line);
    const lineEnd = nl < n ? nl + 1 : n;
    if (line.trim() === "" && !fence.inFence) {
      // Consume trailing blank lines so callers never receive an empty block.
      let j = lineEnd;
      while (j < n) {
        let nl2 = src.indexOf("\n", j);
        if (nl2 === -1) nl2 = n;
        if (src.slice(j, nl2).trim() !== "") break;
        j = nl2 < n ? nl2 + 1 : n;
      }
      blocks.push(src.slice(blockStart, j));
      blockStart = j;
      i = j;
    } else {
      i = lineEnd;
    }
  }

  if (blockStart < n) blocks.push(src.slice(blockStart));
  return blocks;
}

/**
 * For a block that ends inside an unterminated code fence, split it into the
 * prose/markdown preceding the OPEN fence and the code accumulated so far (the
 * opening ```lang line removed). Returns null when the block does not end inside
 * an open fence. Targets the LAST unterminated fence, so an earlier completed
 * fence in the same block stays in `before` and renders normally instead of
 * being swallowed as plain text.
 */
export function parseOpenFence(
  block: string,
): { before: string; code: string } | null {
  let fence = NO_FENCE;
  let openLineStart = -1;
  let i = 0;
  const n = block.length;

  while (i < n) {
    let nl = block.indexOf("\n", i);
    if (nl === -1) nl = n;
    const wasInFence = fence.inFence;
    fence = stepFence(fence, block.slice(i, nl));
    if (!wasInFence && fence.inFence) openLineStart = i;
    i = nl < n ? nl + 1 : n;
  }

  if (!fence.inFence) return null;
  const before = block.slice(0, openLineStart);
  const afterMarker = block.indexOf("\n", openLineStart);
  const code = afterMarker === -1 ? "" : block.slice(afterMarker + 1);
  return { before, code };
}

function findClosingBacktickRun(src: string, start: number): number | null {
  let runLength = 1;
  while (src[start + runLength] === "`") runLength++;

  let cursor = start + runLength;
  while (cursor < src.length) {
    const next = src.indexOf("`", cursor);
    if (next === -1) return null;
    let closingLength = 1;
    while (src[next + closingLength] === "`") closingLength++;
    if (closingLength === runLength) return next + closingLength;
    cursor = next + closingLength;
  }
  return null;
}

function isEscaped(src: string, index: number): boolean {
  let backslashes = 0;
  while (
    index - backslashes - 1 >= 0 &&
    src[index - backslashes - 1] === "\\"
  ) {
    backslashes++;
  }
  return backslashes % 2 === 1;
}

function skipWhitespace(src: string, start: number): number {
  let cursor = start;
  while (/\s/.test(src[cursor] ?? "")) cursor++;
  return cursor;
}

function findTitleEnd(src: string, start: number): number | null {
  const closer = src[start] === "(" ? ")" : src[start];
  let cursor = start + 1;
  while (cursor < src.length) {
    if (src[cursor] === "\\") {
      cursor += 2;
      continue;
    }
    if (src[cursor] === closer) return cursor + 1;
    cursor++;
  }
  return null;
}

function findLinkDestinationEnd(src: string, start: number): number | null {
  let cursor = skipWhitespace(src, start);

  if (src[cursor] === ")") return cursor + 1;

  if (src[cursor] === "<") {
    cursor++;
    while (cursor < src.length && src[cursor] !== ">") {
      if (src[cursor] === "\\") cursor++;
      cursor++;
    }
    if (src[cursor] !== ">") return null;
    cursor++;
  } else {
    let nestedParentheses = 0;
    while (cursor < src.length) {
      if (src[cursor] === "\\") {
        cursor += 2;
        continue;
      }
      if (src[cursor] === "(") nestedParentheses++;
      if (src[cursor] === ")") {
        if (nestedParentheses === 0) return cursor + 1;
        nestedParentheses--;
      }
      if (/\s/.test(src[cursor]) && nestedParentheses === 0) break;
      cursor++;
    }
  }

  const suffixStart = cursor;
  cursor = skipWhitespace(src, cursor);
  if (src[cursor] === ")") return cursor + 1;
  if (cursor === suffixStart || !['"', "'", "("].includes(src[cursor])) {
    return null;
  }

  const titleEnd = findTitleEnd(src, cursor);
  if (titleEnd === null) return null;
  cursor = skipWhitespace(src, titleEnd);
  return src[cursor] === ")" ? cursor + 1 : null;
}

function replaceOpenLinkDestination(
  src: string,
  replacement: (label: string) => string,
): string {
  let cursor = 0;

  while (cursor < src.length) {
    if (src[cursor] === "\\") {
      cursor += 2;
      continue;
    }
    if (src[cursor] === "`") {
      cursor = findClosingBacktickRun(src, cursor) ?? cursor + 1;
      continue;
    }
    if (src[cursor] !== "[") {
      cursor++;
      continue;
    }

    const linkStart =
      cursor > 0 && src[cursor - 1] === "!" && !isEscaped(src, cursor - 1)
        ? cursor - 1
        : cursor;
    const labelStart = cursor + 1;
    let labelDepth = 1;
    cursor++;

    while (cursor < src.length && labelDepth > 0) {
      if (src[cursor] === "\\") {
        cursor += 2;
        continue;
      }
      if (src[cursor] === "`") {
        cursor = findClosingBacktickRun(src, cursor) ?? cursor + 1;
        continue;
      }
      if (src[cursor] === "[") labelDepth++;
      if (src[cursor] === "]") labelDepth--;
      cursor++;
    }

    if (labelDepth > 0 || src[cursor] !== "(") continue;

    const labelEnd = cursor - 1;
    if (findLinkDestinationEnd(src, cursor + 1) === null) {
      return (
        src.slice(0, linkStart) + replacement(src.slice(labelStart, labelEnd))
      );
    }
  }

  return src;
}

export function maskOpenLinkDestination(src: string): string {
  return replaceOpenLinkDestination(src, (label) => label);
}

export function markOpenLinkDestination(
  src: string,
  pendingDestination: string,
): string {
  return replaceOpenLinkDestination(
    src,
    (label) => `[${label}](${pendingDestination})`,
  );
}
