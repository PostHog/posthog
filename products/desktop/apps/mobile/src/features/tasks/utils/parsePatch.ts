export type DiffLineType = "context" | "add" | "delete" | "no-newline";

export interface DiffLine {
  type: DiffLineType;
  content: string;
  // Stable position-based key (the line's index in the original patch
  // string). Used as a React key so we don't trip the no-array-index-key
  // rule when iterating in the renderer.
  key: string;
}

export interface Hunk {
  header: string;
  lines: DiffLine[];
}

// GitHub's `patch` field contains only hunk content (no `diff --git` / `---`
// / `+++` headers). Each hunk starts with `@@ -A,B +C,D @@` followed by lines
// prefixed by ' ' (context), '+' (addition), '-' (deletion), or '\' (no
// newline marker). We don't need line numbers on mobile — the prefix and
// background colour already convey direction.
export function parsePatch(patch: string): Hunk[] {
  const hunks: Hunk[] = [];
  const raw = patch.split("\n");
  let current: Hunk | null = null;

  for (let i = 0; i < raw.length; i++) {
    const line = raw[i];
    if (line.startsWith("@@")) {
      if (current) hunks.push(current);
      current = { header: line, lines: [] };
      continue;
    }
    if (!current) continue;

    let type: DiffLineType;
    if (line.startsWith("+")) type = "add";
    else if (line.startsWith("-")) type = "delete";
    else if (line.startsWith("\\")) type = "no-newline";
    else type = "context";

    current.lines.push({ type, content: line.slice(1), key: String(i) });
  }
  if (current) hunks.push(current);
  return hunks;
}
