export interface ExcludePattern {
  negated: boolean;
  dirOnly: boolean;
  regex: RegExp;
}

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

    // A single malformed pattern must not drop the whole exclude file: skip the
    // offending line rather than letting a RegExp throw propagate out.
    let regex: RegExp;
    try {
      regex = globToRegExp(pattern, anchored);
    } catch {
      continue;
    }
    patterns.push({ negated, dirOnly, regex });
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
  if ((isDir || !pattern.dirOnly) && pattern.regex.test(entryPath)) {
    return true;
  }

  let separatorIndex = entryPath.indexOf("/");
  while (separatorIndex !== -1) {
    if (pattern.regex.test(entryPath.slice(0, separatorIndex))) {
      return true;
    }
    separatorIndex = entryPath.indexOf("/", separatorIndex + 1);
  }
  return false;
}

function trimUnescapedTrailingSpaces(line: string): string {
  // Drop a trailing CR first so CRLF-terminated exclude files don't bake a \r
  // into every pattern (which would make the compiled regex match nothing).
  return line.replace(/\r$/, "").replace(/(?<!\\) +$/, "");
}

function globToRegExp(pattern: string, anchored: boolean): RegExp {
  let source = anchored ? "^" : "^(?:.*/)?";
  let i = 0;

  while (i < pattern.length) {
    const char = pattern[i];
    if (char === "*") {
      if (pattern[i + 1] === "*") {
        if (pattern[i + 2] === "/") {
          // Collapse a run of consecutive `**/` into one `(?:.*/)?`. They are
          // semantically equivalent, and emitting one group per segment would
          // stack overlapping backtracking `.*` groups — catastrophic on a
          // slash-heavy path that fails the final literal (ReDoS).
          source += "(?:.*/)?";
          i += 3;
          while (
            pattern[i] === "*" &&
            pattern[i + 1] === "*" &&
            pattern[i + 2] === "/"
          ) {
            i += 3;
          }
        } else {
          source += ".*";
          i += 2;
        }
      } else {
        source += "[^/]*";
        i += 1;
      }
    } else if (char === "?") {
      source += "[^/]";
      i += 1;
    } else if (char === "[") {
      const classEnd = pattern.indexOf("]", i + 2);
      if (classEnd === -1) {
        source += "\\[";
        i += 1;
      } else {
        let charClass = pattern.slice(i + 1, classEnd);
        if (charClass.startsWith("!")) {
          charClass = `^${charClass.slice(1)}`;
        }
        source += `[${charClass}]`;
        i = classEnd + 1;
      }
    } else if (char === "\\" && i + 1 < pattern.length) {
      source += escapeRegExp(pattern[i + 1]);
      i += 2;
    } else {
      source += escapeRegExp(char);
      i += 1;
    }
  }

  return new RegExp(`${source}$`);
}

function escapeRegExp(char: string): string {
  return /[.*+?^${}()|[\]\\/]/.test(char) ? `\\${char}` : char;
}
