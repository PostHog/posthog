export interface ExcludePattern {
  negated: boolean;
  dirOnly: boolean;
  tokens: GlobToken[];
}

type SimpleGlobToken =
  | { kind: "literal"; value: string }
  | { kind: "one" | "star" | "globstar" | "directories" };

type GlobToken = SimpleGlobToken | { kind: "class"; predicate: RegExp };
type ParsedGlobToken = SimpleGlobToken | { kind: "class"; source: string };

class UnsupportedCharacterClassError extends Error {}

/**
 * Parses gitignore-style pattern lines (comments, negation, dir-only trailing
 * slash, root anchoring, `*`/`?`/`**`/`[...]` globs). Used to re-apply an
 * exclude file's patterns in-process against paths git has already listed, so
 * callers can avoid asking git to walk huge ignored trees.
 */
export function parseExcludePatterns(content: string): ExcludePattern[] {
  const patterns: ExcludePattern[] = [];

  for (const rawLine of content.split("\n")) {
    const line = trimUnescapedTrailingSpaces(rawLine);
    if (!line || line.startsWith("#")) continue;

    let pattern = line;
    let negated = false;
    if (pattern.startsWith("!")) {
      negated = true;
      pattern = pattern.slice(1);
    } else if (pattern.startsWith("\\!") || pattern.startsWith("\\#")) {
      pattern = pattern.slice(1);
    }

    let dirOnly = false;
    if (pattern.endsWith("/")) {
      dirOnly = true;
      pattern = pattern.slice(0, -1);
    }
    if (!pattern) continue;

    const anchored = pattern.includes("/");
    if (pattern.startsWith("/")) {
      pattern = pattern.slice(1);
    }

    let tokens: GlobToken[];
    try {
      tokens = compileGlob(pattern, anchored);
    } catch (error) {
      // Invalid ranges skip one line; unsupported syntax must reach Git fallback.
      if (error instanceof SyntaxError) continue;
      throw error;
    }
    patterns.push({ negated, dirOnly, tokens });
  }

  return patterns;
}

/**
 * Whether a path matches the pattern list, last match wins (gitignore
 * semantics). `entry` may carry a trailing slash to mark a directory, as in
 * `git ls-files --directory` output. A pattern matching a parent directory
 * matches everything beneath it.
 */
export function matchesExcludePatterns(
  entry: string,
  patterns: ExcludePattern[],
): boolean {
  const isDir = entry.endsWith("/");
  const entryPath = isDir ? entry.slice(0, -1) : entry;

  let matched = false;
  for (const pattern of patterns) {
    if (patternMatches(pattern, entryPath, isDir)) {
      matched = !pattern.negated;
    }
  }
  return matched;
}

function patternMatches(
  pattern: ExcludePattern,
  entryPath: string,
  isDir: boolean,
): boolean {
  // Each row records reachable UTF-16 offsets. Reuse rows so ambiguous stars
  // cost O(pattern length * path length), including all parent-directory checks.
  let current = new Uint8Array(entryPath.length + 1);
  let next = new Uint8Array(entryPath.length + 1);
  current[0] = 1;
  for (const token of pattern.tokens) {
    next.fill(0);
    let directoryPrefix = false;
    for (let offset = 0; offset <= entryPath.length; offset++) {
      const char = entryPath[offset];
      if (token.kind === "directories") {
        if (current[offset]) {
          next[offset] = 1;
          directoryPrefix = true;
        }
        if (directoryPrefix && char === "/") next[offset + 1] = 1;
        if (isLineTerminator(char)) directoryPrefix = false;
      } else if (token.kind === "star" || token.kind === "globstar") {
        if (current[offset]) next[offset] = 1;
        if (
          next[offset] &&
          offset < entryPath.length &&
          (token.kind === "star" ? char !== "/" : !isLineTerminator(char))
        ) {
          next[offset + 1] = 1;
        }
      } else if (current[offset] && offset < entryPath.length) {
        const accepts =
          token.kind === "literal"
            ? char === token.value
            : token.kind === "class"
              ? token.predicate.test(char)
              : char !== "/";
        if (accepts) next[offset + 1] = 1;
      }
    }
    [current, next] = [next, current];
  }
  for (let offset = 0; offset < entryPath.length; offset++) {
    if (entryPath[offset] === "/" && current[offset]) return true;
  }
  return (isDir || !pattern.dirOnly) && current[entryPath.length] === 1;
}

function trimUnescapedTrailingSpaces(line: string): string {
  let end = line.endsWith("\r") ? line.length - 1 : line.length;
  while (end > 0 && line[end - 1] === " " && line[end - 2] !== "\\") end--;
  return line.slice(0, end);
}

function isLineTerminator(char: string): boolean {
  return (
    char === "\n" || char === "\r" || char === "\u2028" || char === "\u2029"
  );
}

function compileGlob(pattern: string, anchored: boolean): GlobToken[] {
  const tokens: ParsedGlobToken[] = anchored ? [] : [{ kind: "directories" }];
  let ambiguousClass = false;
  let i = 0;
  let classEnd = pattern.indexOf("]");

  while (i < pattern.length) {
    const char = pattern[i];
    if (char === "*") {
      if (pattern[i + 1] === "*") {
        if (pattern[i + 2] === "/") {
          tokens.push({ kind: "directories" });
          i += 3;
          while (
            pattern[i] === "*" &&
            pattern[i + 1] === "*" &&
            pattern[i + 2] === "/"
          ) {
            i += 3;
          }
        } else {
          tokens.push({ kind: "globstar" });
          i += 2;
        }
      } else {
        tokens.push({ kind: "star" });
        i += 1;
      }
    } else if (char === "?") {
      tokens.push({ kind: "one" });
      i += 1;
    } else if (char === "[") {
      while (classEnd !== -1 && classEnd < i + 2) {
        classEnd = pattern.indexOf("]", classEnd + 1);
      }
      if (classEnd === -1) {
        tokens.push({ kind: "literal", value: "[" });
        i += 1;
      } else {
        let charClass = pattern.slice(i + 1, classEnd);
        if (charClass.startsWith("!")) {
          charClass = `^${charClass.slice(1)}`;
        }
        const source = `[${charClass}]`;
        // A native predicate is safe only if its first unescaped closing bracket
        // is the final code unit. Escapes consume exactly one following unit.
        let closing = 1;
        while (closing < source.length && source[closing] !== "]") {
          closing += source[closing] === "\\" ? 2 : 1;
        }
        if (closing !== source.length - 1) {
          ambiguousClass = true;
        }
        tokens.push({ kind: "class", source });
        i = classEnd + 1;
      }
    } else if (char === "\\" && i + 1 < pattern.length) {
      tokens.push({ kind: "literal", value: pattern[i + 1] });
      i += 2;
    } else {
      tokens.push({ kind: "literal", value: char });
      i += 1;
    }
  }

  if (ambiguousClass) {
    // Compile only to preserve malformed-line skipping. Never execute this
    // expression: an escaped bracket can absorb the generated glob syntax.
    new RegExp(`^${tokens.map(legacyTokenSource).join("")}$`);
    throw new UnsupportedCharacterClassError(
      "Ambiguous exclude character class",
    );
  }
  return tokens.map((token) =>
    token.kind === "class"
      ? { kind: "class", predicate: new RegExp(token.source) }
      : token,
  );
}

function legacyTokenSource(token: ParsedGlobToken): string {
  switch (token.kind) {
    case "literal":
      return ".*+?^$(){}|[]\\/".includes(token.value)
        ? `\\${token.value}`
        : token.value;
    case "class":
      return token.source;
    case "one":
      return "[^/]";
    case "star":
      return "[^/]*";
    case "globstar":
      return ".*";
    case "directories":
      return "(?:.*/)?";
  }
}
