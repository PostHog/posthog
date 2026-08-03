/**
 * Byte-accurate UTF-8 truncation shared by `format.ts` (result summaries) and
 * `lifecycle.ts` (transcript persistence).
 *
 * The naive approach — `while (Buffer.byteLength(s) > cap) s = s.slice(0, -1)`
 * — removes one UTF-16 code unit per iteration and recomputes the byte length
 * of the *entire remaining string* every time, which is O(n) iterations times
 * O(n) work each: quadratic in the number of excess characters. For a large
 * transcript that's a real cost. This does one `Buffer.from(text, "utf8")`
 * encode, then backs off at most 3 bytes to land on a UTF-8 codepoint
 * boundary — O(1) relative to the input size once encoded.
 */
export interface TruncateUtf8Result {
  text: string;
  /** Bytes omitted from the original input. 0 when no truncation was needed. */
  omittedBytes: number;
}

export function truncateUtf8(
  text: string,
  maxBytes: number,
): TruncateUtf8Result {
  const full = Buffer.from(text, "utf8");
  if (full.length <= maxBytes) return { text, omittedBytes: 0 };

  let end = maxBytes;
  // Back off while `full[end]` is a UTF-8 continuation byte (0b10xxxxxx):
  // landing there means the cut falls mid-codepoint, so exclude that whole
  // (now-incomplete) codepoint rather than emitting invalid UTF-8.
  while (end > 0 && (full[end] & 0xc0) === 0x80) end--;

  return {
    text: full.subarray(0, end).toString("utf8"),
    omittedBytes: full.length - end,
  };
}
