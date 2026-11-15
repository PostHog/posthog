// Pure git command-line parsing, shared by the signed-commit guard (hooks.ts)
// and the RTK rewrite (session/rtk.ts). Kept dependency-free so importers don't
// drag in the hooks module's heavier import chain.

// git global options that consume the following token as their value, so the
// subcommand detector must skip both (mirrors the sandbox `git` PATH shim).
const GIT_VALUE_FLAGS = new Set([
  "-C",
  "-c",
  "--git-dir",
  "--work-tree",
  "--namespace",
  "--exec-path",
]);

/**
 * Returns the git subcommand of a single shell segment (e.g. "status" for
 * `git -C repo status`), or null when the segment isn't a git invocation.
 * A leading path is stripped so `/usr/bin/git` is still recognised as git.
 */
export function gitSubcommand(segment: string): string | null {
  const tokens = segment.trim().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return null;
  // Strip a leading path so `/usr/bin/git` is still recognised as git.
  const head = tokens[0].split("/").pop();
  if (head !== "git") return null;

  let skipNext = false;
  for (const tok of tokens.slice(1)) {
    if (skipNext) {
      skipNext = false;
      continue;
    }
    if (GIT_VALUE_FLAGS.has(tok)) {
      skipNext = true;
      continue;
    }
    if (tok.startsWith("-")) continue;
    return tok;
  }
  return null;
}
