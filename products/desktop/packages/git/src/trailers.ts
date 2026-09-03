// Standalone (no git-saga / simple-git imports) so signed-commit.ts can append
// PostHog trailers without dragging the heavy git machinery into bundles that
// reach it (e.g. the renderer's browser build).
export function buildPostHogTrailers(taskId?: string): string[] {
  const trailers = ["Generated-By: PostHog Desktop"];
  if (taskId) trailers.push(`Task-Id: ${taskId}`);
  return trailers;
}

// Claude Code adds these to the commit message by default. Some CI systems gate
// preview builds on commit author identity and cannot allowlist the address, so
// the trailer breaks the deployment. Strip it here instead of relying on the
// prompt, which the model does not always follow.
const CLAUDE_COAUTHOR_RE = /^\s*co-authored-by:\s*.*noreply@anthropic\.com.*$/i;
const CLAUDE_GENERATED_RE = /generated with \[claude code\]/i;

/** Removes Claude Code's default attribution lines from a commit message. */
export function stripClaudeAttribution(message: string | undefined): string {
  if (!message) return "";
  return message
    .split("\n")
    .filter(
      (line) =>
        !CLAUDE_COAUTHOR_RE.test(line) && !CLAUDE_GENERATED_RE.test(line),
    )
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
