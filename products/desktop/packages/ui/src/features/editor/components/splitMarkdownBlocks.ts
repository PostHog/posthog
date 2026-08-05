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
