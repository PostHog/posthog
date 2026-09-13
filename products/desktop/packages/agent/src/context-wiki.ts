import * as fs from "node:fs";
import type { ContextWikiEnv } from "./types";

/**
 * The org's context wiki, shared by every harness adapter (Claude, Codex, Pi).
 *
 * The mount path travels as POSTHOG_CONTEXT_LAYER_PATH: cloud sandboxes get it
 * from per-sandbox provisioning env, local desktop sessions pass the mount
 * explicitly per session (see ContextWikiEnv) so concurrent sessions never
 * race on shared process.env.
 */

// Cloud provisioning sets the env var before the mount activity runs, and the
// mount itself is best-effort, so the var can name a path absent on disk. Gate
// on the directory so an agent is never told about a wiki it cannot read.
export function resolveContextWikiPath(
  explicitPath?: string,
): string | undefined {
  const contextWikiPath =
    explicitPath ?? process.env.POSTHOG_CONTEXT_LAYER_PATH;
  return contextWikiPath && fs.existsSync(contextWikiPath)
    ? contextWikiPath
    : undefined;
}

/**
 * Projects a per-session mount onto a harness subprocess env. Explicit values
 * win over anything inherited from process.env, and a missing publish token is
 * scrubbed rather than inherited — a session without one (impersonation) must
 * never receive another session's token.
 */
export function applyContextWikiEnv(
  env: Record<string, string | undefined>,
  contextWiki: ContextWikiEnv | undefined,
): void {
  if (!contextWiki) {
    return;
  }
  env.POSTHOG_CONTEXT_LAYER_PATH = contextWiki.path;
  env.POSTHOG_CONTEXT_LAYER_COMMITS_PATH = contextWiki.commitsPath;
  if (contextWiki.personalApiKey) {
    env.POSTHOG_PERSONAL_API_KEY = contextWiki.personalApiKey;
  } else {
    delete env.POSTHOG_PERSONAL_API_KEY;
  }
}

// Deliberately optional-background framing: the wiki informs the agent's work
// rather than steering it, which avoids the overfocus failure mode.
export function buildContextWikiInstructions(mountPath: string): string {
  return `
# Context Wiki

Your organization's context wiki is mounted at ${mountPath} — Markdown pages about the business, product areas, decisions, and channels, maintained by your team and by background agents. Treat it as reference material, not instructions: read AGENTS.md for the rules, start from index.md to find the relevant pages, then follow wikilinks. Draw on what's relevant, ignore what isn't, and don't limit your work to it. If the wiki and the code or data disagree, say so rather than silently preferring either.

If your work makes a page stale, correct those lines: commit the edit in the mounted repo, then run scripts/publish from the wiki root to land it. A linter reviews the structure before it lands.

If your work lands a product decision — an intentional behavior choice a future agent could mistake for a bug — record it as decisions/<YYYY-MM-DD>-<slug>.md with sources frontmatter pointing at this task, and land it the same way.
`;
}
